from flask import Flask, render_template, request, abort, redirect, url_for
from sqlalchemy import create_engine, inspect, text, MetaData
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from functools import lru_cache
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_all_tables():
    """Return sorted list of all table names in the database."""
    inspector = inspect(engine)
    return sorted(inspector.get_table_names())


@lru_cache(maxsize=None)
def get_table_meta(table_name):
    """Return (columns, pk_cols, fk_map) for a table.

    fk_map: {local_col: (referred_table, referred_col)}
    """
    inspector = inspect(engine)
    columns = inspector.get_columns(table_name)
    pk = inspector.get_pk_constraint(table_name)
    fks = inspector.get_foreign_keys(table_name)

    fk_map = {}
    for fk in fks:
        for local_col, ref_col in zip(
            fk['constrained_columns'], fk['referred_columns']
        ):
            fk_map[local_col] = (fk['referred_table'], ref_col)

    pk_cols = pk.get('constrained_columns', [])
    return columns, pk_cols, fk_map


@lru_cache(maxsize=1)
def get_reverse_fk_map():
    """Build a map of {table_name: [(referencing_table, local_col, ref_col), ...]}.

    This allows the record detail page to find all records in other tables that
    reference a given table's primary key.
    """
    reverse = {}
    for table_name in get_all_tables():
        _, _, fk_map = get_table_meta(table_name)
        for local_col, (ref_table, ref_col) in fk_map.items():
            reverse.setdefault(ref_table, []).append(
                (table_name, local_col, ref_col)
            )
    return reverse


def validate_table(table_name):
    """Abort with 404 if table_name is not in the database."""
    if table_name not in get_all_tables():
        abort(404)


def table_row_count(table_name):
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM `{table_name}`")
        ).scalar()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    try:
        tables = get_all_tables()
        table_stats = {}
        for tbl in tables:
            _, _, fk_map = get_table_meta(tbl)
            inspector = inspect(engine)
            cols = inspector.get_columns(tbl)
            table_stats[tbl] = {
                'column_count': len(cols),
                'fk_count': len(fk_map),
            }
        return render_template('index.html', tables=tables, table_stats=table_stats)
    except OperationalError as exc:
        return render_template('error.html', error=str(exc)), 500


@app.route('/table/<table_name>')
def browse_table(table_name):
    validate_table(table_name)
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    per_page = config.PER_PAGE

    try:
        columns, pk_cols, fk_map = get_table_meta(table_name)
        col_names = [c['name'] for c in columns]

        # Identify text-like columns for search
        text_cols = [
            c['name'] for c in columns
            if any(
                t in str(c['type']).lower()
                for t in ('char', 'text', 'enum', 'set')
            )
        ]

        with engine.connect() as conn:
            if search and text_cols:
                where_parts = ' OR '.join(
                    [f"`{col}` LIKE :search" for col in text_cols]
                )
                where_clause = f"WHERE {where_parts}"
                params = {
                    'search': f'%{search}%',
                    'limit': per_page,
                    'offset': (page - 1) * per_page,
                }
                total = conn.execute(
                    text(f"SELECT COUNT(*) FROM `{table_name}` {where_clause}"),
                    {'search': f'%{search}%'},
                ).scalar()
                rows = conn.execute(
                    text(
                        f"SELECT * FROM `{table_name}` {where_clause}"
                        " LIMIT :limit OFFSET :offset"
                    ),
                    params,
                ).fetchall()
            else:
                total = conn.execute(
                    text(f"SELECT COUNT(*) FROM `{table_name}`")
                ).scalar()
                rows = conn.execute(
                    text(
                        f"SELECT * FROM `{table_name}`"
                        " LIMIT :limit OFFSET :offset"
                    ),
                    {'limit': per_page, 'offset': (page - 1) * per_page},
                ).fetchall()

        total_pages = max(1, (total + per_page - 1) // per_page)

        return render_template(
            'table.html',
            table_name=table_name,
            columns=col_names,
            rows=rows,
            pk_cols=pk_cols,
            fk_map=fk_map,
            page=page,
            total_pages=total_pages,
            total=total,
            search=search,
            per_page=per_page,
        )
    except SQLAlchemyError as exc:
        return render_template('error.html', error=str(exc)), 500


@app.route('/table/<table_name>/record/<path:pk_value>')
def view_record(table_name, pk_value):
    validate_table(table_name)

    try:
        columns, pk_cols, fk_map = get_table_meta(table_name)
        col_names = [c['name'] for c in columns]

        if not pk_cols:
            abort(400)

        # Support composite PKs encoded as "val1/val2"
        pk_values = pk_value.split('/')
        if len(pk_values) != len(pk_cols):
            abort(400)

        where_parts = ' AND '.join(
            [f"`{col}` = :pk_{col}" for col in pk_cols]
        )
        params = {f'pk_{col}': val for col, val in zip(pk_cols, pk_values)}

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT * FROM `{table_name}` WHERE {where_parts} LIMIT 1"
                ),
                params,
            ).fetchone()

        if row is None:
            abort(404)

        record = dict(zip(col_names, row))

        # Build forward FK targets (col -> (ref_table, ref_col, value))
        fk_targets = {}
        for col, (ref_table, ref_col) in fk_map.items():
            fk_targets[col] = (ref_table, ref_col, record.get(col))

        # Build reverse FK relations: other tables that reference this table
        reverse_map = get_reverse_fk_map()
        related_records = {}
        for ref_table, local_col, ref_col in reverse_map.get(table_name, []):
            ref_value = record.get(ref_col)
            if ref_value is None:
                continue
            _, ref_pk_cols, _ = get_table_meta(ref_table)
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        f"SELECT * FROM `{ref_table}`"
                        f" WHERE `{local_col}` = :val LIMIT 25"
                    ),
                    {'val': ref_value},
                ).fetchall()
            if rows:
                ref_columns = [
                    c['name']
                    for c in inspect(engine).get_columns(ref_table)
                ]
                related_records[ref_table] = {
                    'columns': ref_columns,
                    'rows': [dict(zip(ref_columns, r)) for r in rows],
                    'pk_cols': ref_pk_cols,
                    'local_col': local_col,
                    'ref_col': ref_col,
                }

        return render_template(
            'record.html',
            table_name=table_name,
            record=record,
            pk_cols=pk_cols,
            fk_map=fk_map,
            fk_targets=fk_targets,
            related_records=related_records,
            col_names=col_names,
        )
    except SQLAlchemyError as exc:
        return render_template('error.html', error=str(exc)), 500


@app.route('/table/<table_name>/lookup/<column>/<path:value>')
def lookup_record(table_name, column, value):
    """Resolve a row by column/value and redirect to its record detail page."""
    validate_table(table_name)

    try:
        columns, pk_cols, _ = get_table_meta(table_name)
        col_names = [c['name'] for c in columns]

        if not pk_cols:
            abort(400)
        if column not in col_names:
            abort(404)

        select_pk_cols = ', '.join([f"`{col}`" for col in pk_cols])
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT {select_pk_cols} FROM `{table_name}`"
                    f" WHERE `{column}` = :value LIMIT 1"
                ),
                {'value': value},
            ).fetchone()

        if row is None:
            abort(404)

        pk_path = '/'.join([str(v) for v in row])
        return redirect(
            url_for('view_record', table_name=table_name, pk_value=pk_path)
        )
    except SQLAlchemyError as exc:
        return render_template('error.html', error=str(exc)), 500


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

@app.template_filter('nl2br')
def nl2br_filter(value):
    if value is None:
        return ''
    return str(value).replace('\n', '<br>')


@app.context_processor
def inject_tables():
    try:
        return {'all_tables': get_all_tables()}
    except Exception:
        return {'all_tables': []}


if __name__ == '__main__':
    app.run(debug=config.DEBUG, host='0.0.0.0', port=3000)
