from sqlalchemy.sql import literal_column, expression, func, select
from sqlalchemy import String
from dj_eden_app.stage_data import stage

"Flag computation per Bryan McCloskey, USGS"

"""
The logic for flags displayed to the public for hourly data should be:
  if (flag=="M") "M"; elseif (stage < dry_elevation) "D"; elseif (flag==NULL) "O"; else "E"
(We should explicitly flag measured values "O" [observed] rather than just leave them NULL.)
"""

# These are not strictly required, but make the generated SQL a little more self-contained.
_M = literal_column("'M'", String)  # The M flag is redundant with null data
_D = literal_column("'D'", String)
_O = literal_column("'O'", String)
_E = literal_column("'E'", String)

def hourly_data_expr(flag_expr, value_expr, dry_elev):
    flag = expression.case([
                            (flag_expr == _M, _M),
                            (value_expr == None, _M),
                            (value_expr < dry_elev, _D),
                            (flag_expr == None, _O)],
                           else_=_E)
    return (flag, value_expr)


"""
The logic for flags displayed for daily means should be:
  if (length(flag=="M")==24) "M"; elseif (mean(stage) < dry_elevation) "D"; elseif (length(flag==NULL)>0) "O"; else "E"
I.e., if _all_ 24 hourly values are missing, flag "M"; if the daily mean is below the "goes dry" value, flag "D"; if _any_ of the daily values are measured, flag "O"; else flag as estimated ("E").
"""

# if any O then (if v < dry then D else O)
# if any E then (if v < dry then D else E)
# else (all M) M

# so (v == None) -> None
# (v < dry) -> D
# else max(flag)

# note that avg(all nulls) -> null
# note that max('M','O') -> 'O'

def daily_data_expr(flag_expr, value_expr, dry_elev):
    flag_expr = expression.case([
                                 (flag_expr == None, _O)
                                 ],
                                else_=flag_expr)
    flag_expr = expression.case([
                            (func.avg(value_expr) == None, _M),
                            (func.avg(value_expr) < dry_elev, _D),
                            ],
                           else_=func.max(flag_expr)
                           )
    return (flag_expr, func.avg(value_expr))

def date_col():
    return stage.c['datetime']

def flag_col(g):
    return stage.c['flag_' + g]

def value_col(g):
    return stage.c['stage_' + g]

def hourly_query_1(gage, dry_value):
    "Query for hourly data for single gage.  Result will have three columns: datetime, data (or none), flag."
    dt = date_col()

    # base query, raw values
    query_by_hour = select([dt])
    f = flag_col(gage)
    s = value_col(gage)
    (flag, val) = hourly_data_expr(f, s, dry_value)
    query_by_hour = query_by_hour.column(val.label('data'))
    query_by_hour = query_by_hour.column(flag.label('flag'))

    return query_by_hour

def daily_query_1(gage, dry_value):
    "Query for daily average data for single gage.  Result will have these columns: date, averaged data (or None), flag, min, max, count"
    dt = date_col()
    date = func.date(dt)
    dm = func.min(date).label("date")

    # base query, daily means
    query_by_day = select([dm]).group_by(date)
    f = flag_col(gage)
    s = value_col(gage)
    (flag, val) = daily_data_expr(f, s, dry_value)
    query_by_day = query_by_day.column(val.label('average'))
    query_by_day = query_by_day.column(flag.label('flag'))
    # just to verify that we are really grouping
    query_by_day = query_by_day.column(func.min(s).label("min"))
    query_by_day = query_by_day.column(func.max(s).label("max"))
    query_by_day = query_by_day.column(func.count(dt).label("count"))

    return query_by_day

if __name__ == '__main__':
    gages = ['2A300', 'G-3567']

    dt = stage.c['datetime']

    # these queries could be pulled out to a multi-station query -- parameters would be station objects to get dry values

    # base query, raw values
    query_by_hour = select([dt])
    for g in gages:
        f = flag_col(g)
        s = value_col(g)
        (flag, val) = hourly_data_expr(f, s, 4.2)
        query_by_hour = query_by_hour.column(val.label(g))
        query_by_hour = query_by_hour.column(flag.label(g + ' flag'))

    print "hourly"
    print str(query_by_hour)


    # base query, daily means
    dm = func.min(func.date(dt))
    date = dm.label("date")
    query_by_day = select([date]).group_by(func.date(dt))
    for g in gages:
        f = flag_col(g)
        s = value_col(g)
        (flag, val) = daily_data_expr(f, s, 4.5)
        query_by_day = query_by_day.column(val.label(g + ' avg'))
        query_by_day = query_by_day.column(flag.label(g + ' flag'))
    # just to verify that we are really grouping
    query_by_day = query_by_day.column(func.count(dt).label("ct"))

    print "daily"
    print str(query_by_day)

    def _show(q):
        "Exercise a query"
        rs = q.execute()
        print "\t", rs.keys()
        vv = rs.fetchmany(30)
        for v in vv:
            print "\t", v

    # does it really work?
    q = query_by_day.where(dt >= '2001-01-01')
    _show(q)

    # single-gage queries
    print "daily query"
    q = daily_query_1('G-3567', 4.9)
    q = q.where(dt >= '2003-06-28')
    print str(q)
    _show(q)


