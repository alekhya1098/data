import json
import os
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}

GROUP_BY_MAP = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "yearly": "year",
}

ORGANIZATION_TYPE_MAP = {
    "non_profit": "non_profit",
    "for_profit": "for_profit",
}


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def get_default_response():
    return {
        "summary": {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0,
        },
        "growth_trend": [],
        "organizations_by_location": [],
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
        "rating_distribution": [],
        "organization_type_distribution": [],
    }


def get_db_connection():
    """
    Uses local/environment-based database configuration.

    Do not hardcode production credentials or AWS Parameter Store paths.
    """
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


def get_event_body(event):
    if not event:
        return {}

    if "body" in event:
        body = event.get("body")

        if isinstance(body, str):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {}

        if isinstance(body, dict):
            return body

    return event


def validate_filters(filters):
    time_filter = str(filters.get("time_filter", "ALL")).upper()
    group_by = str(filters.get("group_by", "daily")).lower()
    organization_type = str(
        filters.get("organization_type", "ALL")
    ).lower()

    if time_filter not in VALID_TIME_FILTERS:
        return (
            False,
            f"Invalid time_filter. Supported values: "
            f"{', '.join(sorted(VALID_TIME_FILTERS))}",
        )

    if group_by not in GROUP_BY_MAP:
        return (
            False,
            "Invalid group_by. Supported values: "
            "daily, weekly, monthly, yearly",
        )

    if organization_type not in {
        "all",
        "non_profit",
        "for_profit",
    }:
        return (
            False,
            "Invalid organization_type. Supported values: "
            "ALL, non_profit, for_profit",
        )

    if time_filter == "CUSTOM":
        start_date = filters.get("start_date")
        end_date = filters.get("end_date")

        if not start_date or not end_date:
            return (
                False,
                "CUSTOM time_filter requires both start_date and end_date",
            )

        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            return (
                False,
                "start_date and end_date must use YYYY-MM-DD format",
            )

        if start > end:
            return (
                False,
                "start_date cannot be after end_date",
            )

    return True, None


def check_is_contributor_available(cursor):
    """
    The issue notes that is_contributor may not yet exist in the
    development DB. Detect it dynamically so the API does not fail.
    """
    query = """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'organizations'
              AND column_name = 'is_contributor'
        ) AS column_exists;
    """

    cursor.execute(query, (SCHEMA_NAME,))
    row = cursor.fetchone()

    return bool(row and row["column_exists"])


def build_filters(
    filters,
    include_region=True,
    include_time=True,
):
    conditions = []
    params = []

    time_filter = str(
        filters.get("time_filter", "ALL")
    ).upper()

    if include_time:
        if time_filter == "7D":
            conditions.append(
                "o.created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'"
            )

        elif time_filter == "30D":
            conditions.append(
                "o.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'"
            )

        elif time_filter == "1Y":
            conditions.append(
                "o.created_at >= CURRENT_TIMESTAMP - INTERVAL '1 year'"
            )

        elif time_filter == "CUSTOM":
            conditions.append("o.created_at >= %s")
            params.append(filters["start_date"])

            conditions.append(
                "o.created_at < (%s::date + INTERVAL '1 day')"
            )
            params.append(filters["end_date"])

    region = filters.get("region", "ALL")

    if (
        include_region
        and region
        and str(region).upper() != "ALL"
    ):
        conditions.append(
            "("
            "LOWER(s.state_name) = LOWER(%s) "
            "OR UPPER(o.state_id) = UPPER(%s)"
            ")"
        )
        params.extend([region, region])

    organization_type = str(
        filters.get("organization_type", "ALL")
    ).lower()

    if organization_type != "all":
        db_value = ORGANIZATION_TYPE_MAP[organization_type]

        conditions.append(
            "LOWER(REPLACE(o.org_type::text, '-', '_')) = %s"
        )
        params.append(db_value)

    if conditions:
        return "WHERE " + " AND ".join(conditions), params

    return "", params


def fetch_summary(cursor, filters, contributor_available):
    where_clause, params = build_filters(filters)

    contributor_expression = (
        """
        COUNT(*) FILTER (
            WHERE o.is_contributor = TRUE
        )
        """
        if contributor_available
        else "0"
    )

    query = f"""
        SELECT
            COUNT(*) AS total_organizations,

            COUNT(*) FILTER (
                WHERE o.is_collaborator = TRUE
            ) AS total_collaborators,

            {contributor_expression}
                AS total_contributors,

            ROUND(
                AVG(o.org_rating)::numeric,
                2
            ) AS average_org_rating

        FROM {SCHEMA_NAME}.organizations o

        LEFT JOIN {SCHEMA_NAME}.states s
            ON o.state_id = s.state_id

        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "total_organizations": int(
            row["total_organizations"] or 0
        ),
        "total_collaborators": int(
            row["total_collaborators"] or 0
        ),
        "total_contributors": int(
            row["total_contributors"] or 0
        ),
        "average_org_rating": (
            float(row["average_org_rating"])
            if row["average_org_rating"] is not None
            else 0
        ),
    }


def fetch_growth_trend(cursor, filters):
    group_by = str(
        filters.get("group_by", "daily")
    ).lower()

    interval = GROUP_BY_MAP[group_by]

    time_filter = str(
        filters.get("time_filter", "ALL")
    ).upper()

    # ALL does not require a pre-range baseline.
    if time_filter == "ALL":
        where_clause, params = build_filters(
            filters
        )

        query = f"""
            WITH period_counts AS (
                SELECT
                    DATE_TRUNC(
                        '{interval}',
                        o.created_at
                    ) AS period,

                    COUNT(*) AS organizations_added,

                    COUNT(*) FILTER (
                        WHERE o.is_collaborator IS TRUE
                    ) AS collaborators_added

                FROM {SCHEMA_NAME}.organizations o

                LEFT JOIN {SCHEMA_NAME}.states s
                    ON o.state_id = s.state_id

                {where_clause}

                GROUP BY 1
            )

            SELECT
                period,

                SUM(organizations_added)
                    OVER (
                        ORDER BY period
                        ROWS BETWEEN UNBOUNDED PRECEDING
                        AND CURRENT ROW
                    ) AS total_organizations,

                SUM(collaborators_added)
                    OVER (
                        ORDER BY period
                        ROWS BETWEEN UNBOUNDED PRECEDING
                        AND CURRENT ROW
                    ) AS total_collaborators

            FROM period_counts

            ORDER BY period;
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()

    else:
        # Apply region / organization type to both the baseline
        # and selected period, but do not apply the date filter yet.
        non_date_where, non_date_params = build_filters(
            filters,
            include_time=False,
        )

        if time_filter == "7D":
            start_expression = (
                "CURRENT_TIMESTAMP - INTERVAL '7 days'"
            )
            period_date_condition = (
                "o.created_at >= "
                "CURRENT_TIMESTAMP - INTERVAL '7 days'"
            )

            baseline_params = list(
                non_date_params
            )
            period_params = list(
                non_date_params
            )

        elif time_filter == "30D":
            start_expression = (
                "CURRENT_TIMESTAMP - INTERVAL '30 days'"
            )
            period_date_condition = (
                "o.created_at >= "
                "CURRENT_TIMESTAMP - INTERVAL '30 days'"
            )

            baseline_params = list(
                non_date_params
            )
            period_params = list(
                non_date_params
            )

        elif time_filter == "1Y":
            start_expression = (
                "CURRENT_TIMESTAMP - INTERVAL '1 year'"
            )
            period_date_condition = (
                "o.created_at >= "
                "CURRENT_TIMESTAMP - INTERVAL '1 year'"
            )

            baseline_params = list(
                non_date_params
            )
            period_params = list(
                non_date_params
            )

        else:  # CUSTOM
            start_expression = "%s::timestamp"

            period_date_condition = (
                "o.created_at >= %s "
                "AND o.created_at < "
                "(%s::date + INTERVAL '1 day')"
            )

            baseline_params = (
                list(non_date_params)
                + [filters["start_date"]]
            )

            period_params = (
                list(non_date_params)
                + [
                    filters["start_date"],
                    filters["end_date"],
                ]
            )

        baseline_where = (
            f"{non_date_where} AND "
            f"o.created_at < {start_expression}"
            if non_date_where
            else
            f"WHERE o.created_at < {start_expression}"
        )

        period_where = (
            f"{non_date_where} AND "
            f"{period_date_condition}"
            if non_date_where
            else
            f"WHERE {period_date_condition}"
        )

        query = f"""
            WITH baseline AS (
                SELECT
                    COUNT(*) AS organizations_before,

                    COUNT(*) FILTER (
                        WHERE o.is_collaborator IS TRUE
                    ) AS collaborators_before

                FROM {SCHEMA_NAME}.organizations o

                LEFT JOIN {SCHEMA_NAME}.states s
                    ON o.state_id = s.state_id

                {baseline_where}
            ),

            period_counts AS (
                SELECT
                    DATE_TRUNC(
                        '{interval}',
                        o.created_at
                    ) AS period,

                    COUNT(*) AS organizations_added,

                    COUNT(*) FILTER (
                        WHERE o.is_collaborator IS TRUE
                    ) AS collaborators_added

                FROM {SCHEMA_NAME}.organizations o

                LEFT JOIN {SCHEMA_NAME}.states s
                    ON o.state_id = s.state_id

                {period_where}

                GROUP BY 1
            )

            SELECT
                pc.period,

                b.organizations_before
                +
                SUM(pc.organizations_added)
                    OVER (
                        ORDER BY pc.period
                        ROWS BETWEEN UNBOUNDED PRECEDING
                        AND CURRENT ROW
                    ) AS total_organizations,

                b.collaborators_before
                +
                SUM(pc.collaborators_added)
                    OVER (
                        ORDER BY pc.period
                        ROWS BETWEEN UNBOUNDED PRECEDING
                        AND CURRENT ROW
                    ) AS total_collaborators

            FROM period_counts pc

            CROSS JOIN baseline b

            ORDER BY pc.period;
        """

        params = (
            baseline_params
            + period_params
        )

        cursor.execute(query, params)
        rows = cursor.fetchall()

    return [
        {
            "period": row["period"],
            "total_organizations": int(
                row["total_organizations"] or 0
            ),
            "total_collaborators": int(
                row["total_collaborators"] or 0
            ),
        }
        for row in rows
    ]

def fetch_organizations_by_location(cursor, filters):
    where_clause, params = build_filters(filters)

    state_query = f"""
        WITH state_counts AS (
            SELECT
                o.state_id,
                s.state_name,
                COUNT(*) AS organization_count

            FROM {SCHEMA_NAME}.organizations o

            LEFT JOIN {SCHEMA_NAME}.states s
                ON o.state_id = s.state_id

            {where_clause}

            GROUP BY
                o.state_id,
                s.state_name
        ),

        total AS (
            SELECT
                COALESCE(
                    SUM(organization_count),
                    0
                ) AS total_count
            FROM state_counts
        )

        SELECT
            sc.state_id,
            sc.state_name,
            sc.organization_count,

            CASE
                WHEN t.total_count > 0
                THEN ROUND(
                    (
                        sc.organization_count::numeric
                        / t.total_count
                    ) * 100,
                    2
                )
                ELSE 0
            END AS percentage

        FROM state_counts sc

        CROSS JOIN total t

        ORDER BY
            sc.organization_count DESC,
            sc.state_name;
    """

    cursor.execute(state_query, params)
    state_rows = cursor.fetchall()

    city_query = f"""
        WITH city_counts AS (
            SELECT
                o.city_name,
                o.state_id,
                s.state_name,
                COUNT(*) AS organization_count

            FROM {SCHEMA_NAME}.organizations o

            LEFT JOIN {SCHEMA_NAME}.states s
                ON o.state_id = s.state_id

            {where_clause}

            GROUP BY
                o.city_name,
                o.state_id,
                s.state_name
        ),

        total AS (
            SELECT
                COALESCE(
                    SUM(organization_count),
                    0
                ) AS total_count
            FROM city_counts
        )

        SELECT
            cc.city_name,
            cc.state_id,
            cc.state_name,
            cc.organization_count,

            CASE
                WHEN t.total_count > 0
                THEN ROUND(
                    (
                        cc.organization_count::numeric
                        / t.total_count
                    ) * 100,
                    2
                )
                ELSE 0
            END AS percentage

        FROM city_counts cc

        CROSS JOIN total t

        ORDER BY
            cc.organization_count DESC,
            cc.city_name;
    """

    cursor.execute(city_query, params)
    city_rows = cursor.fetchall()

    return {
        "by_state": [
            {
                "state_id": row["state_id"],
                "state_name": row["state_name"],
                "organization_count": int(
                    row["organization_count"] or 0
                ),
                "percentage": float(
                    row["percentage"] or 0
                ),
            }
            for row in state_rows
        ],

        "by_city": [
            {
                "city_name": row["city_name"],
                "state_id": row["state_id"],
                "state_name": row["state_name"],
                "organization_count": int(
                    row["organization_count"] or 0
                ),
                "percentage": float(
                    row["percentage"] or 0
                ),
            }
            for row in city_rows
        ],
    }

def fetch_organizations_by_size(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            LOWER(o.org_size) AS org_size,
            COUNT(*) AS organization_count

        FROM {SCHEMA_NAME}.organizations o

        LEFT JOIN {SCHEMA_NAME}.states s
            ON o.state_id = s.state_id

        {where_clause}

        GROUP BY LOWER(o.org_size)

        ORDER BY organization_count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "org_size": row["org_size"],
            "organization_count": int(
                row["organization_count"] or 0
            ),
        }
        for row in rows
    ]


def fetch_collaborator_vs_contributor(
    cursor,
    filters,
    contributor_available,
):
    where_clause, params = build_filters(filters)

    if contributor_available:
        query = f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE o.is_collaborator IS TRUE
                      AND o.is_contributor IS NOT TRUE
                ) AS collaborator_only_count,

                COUNT(*) FILTER (
                    WHERE o.is_collaborator IS NOT TRUE
                      AND o.is_contributor IS TRUE
                ) AS contributor_only_count,

                COUNT(*) FILTER (
                    WHERE o.is_collaborator IS TRUE
                      AND o.is_contributor IS TRUE
                ) AS both_count,

                COUNT(*) FILTER (
                    WHERE o.is_collaborator IS NOT TRUE
                      AND o.is_contributor IS NOT TRUE
                ) AS neither_count

            FROM {SCHEMA_NAME}.organizations o

            LEFT JOIN {SCHEMA_NAME}.states s
                ON o.state_id = s.state_id

            {where_clause};
        """

        cursor.execute(query, params)
        row = cursor.fetchone()

        collaborator_only_count = int(
            row["collaborator_only_count"] or 0
        )
        contributor_only_count = int(
            row["contributor_only_count"] or 0
        )
        both_count = int(
            row["both_count"] or 0
        )
        neither_count = int(
            row["neither_count"] or 0
        )

        total = (
            collaborator_only_count
            + contributor_only_count
            + both_count
            + neither_count
        )

        def percentage(count):
            return (
                round(count / total * 100, 2)
                if total
                else 0
            )

        return [
            {
                "type": "collaborator_only",
                "organization_count": collaborator_only_count,
                "percentage": percentage(
                    collaborator_only_count
                ),
            },
            {
                "type": "contributor_only",
                "organization_count": contributor_only_count,
                "percentage": percentage(
                    contributor_only_count
                ),
            },
            {
                "type": "both",
                "organization_count": both_count,
                "percentage": percentage(
                    both_count
                ),
            },
            {
                "type": "neither",
                "organization_count": neither_count,
                "percentage": percentage(
                    neither_count
                ),
            },
        ]

    query = f"""
        SELECT
            COUNT(*) FILTER (
                WHERE o.is_collaborator IS TRUE
            ) AS collaborator_count,

            COUNT(*) FILTER (
                WHERE o.is_collaborator IS NOT TRUE
            ) AS non_collaborator_count

        FROM {SCHEMA_NAME}.organizations o

        LEFT JOIN {SCHEMA_NAME}.states s
            ON o.state_id = s.state_id

        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    collaborator_count = int(
        row["collaborator_count"] or 0
    )
    non_collaborator_count = int(
        row["non_collaborator_count"] or 0
    )

    total = collaborator_count + non_collaborator_count

    def percentage(count):
        return (
            round(count / total * 100, 2)
            if total
            else 0
        )

    return [
        {
            "type": "collaborator",
            "organization_count": collaborator_count,
            "percentage": percentage(
                collaborator_count
            ),
        },
        {
            "type": "non_collaborator",
            "organization_count": non_collaborator_count,
            "percentage": percentage(
                non_collaborator_count
            ),
        },
    ]


def fetch_rating_distribution(cursor, filters):
    where_clause, params = build_filters(filters)

    if where_clause:
        rating_where = (
            where_clause
            + " AND o.org_rating IS NOT NULL"
        )
    else:
        rating_where = (
            "WHERE o.org_rating IS NOT NULL"
        )

    query = f"""
        WITH ratings AS (
            SELECT generate_series(1, 5) AS rating
        ),

        rating_counts AS (
            SELECT
                o.org_rating AS rating,
                COUNT(*) AS organization_count

            FROM {SCHEMA_NAME}.organizations o

            LEFT JOIN {SCHEMA_NAME}.states s
                ON o.state_id = s.state_id

            {rating_where}

            GROUP BY o.org_rating
        )

        SELECT
            r.rating,
            COALESCE(
                rc.organization_count,
                0
            ) AS organization_count

        FROM ratings r

        LEFT JOIN rating_counts rc
            ON r.rating = rc.rating

        ORDER BY r.rating;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "rating": int(row["rating"]),
            "organization_count": int(
                row["organization_count"] or 0
            ),
        }
        for row in rows
    ]


def fetch_organization_type_distribution(
    cursor,
    filters,
):
    where_clause, params = build_filters(filters)

    group_by = str(
        filters.get("group_by", "daily")
    ).lower()

    interval = GROUP_BY_MAP[group_by]

    query = f"""
        SELECT
            DATE_TRUNC(
                '{interval}',
                o.created_at
            ) AS period,

            COUNT(*) FILTER (
                WHERE LOWER(
                    REPLACE(o.org_type::text, '-', '_')
                ) = 'for_profit'
            ) AS for_profit,

            COUNT(*) FILTER (
                WHERE LOWER(
                    REPLACE(o.org_type::text, '-', '_')
                ) = 'non_profit'
            ) AS non_profit,

            COUNT(*) AS total

        FROM {SCHEMA_NAME}.organizations o

        LEFT JOIN {SCHEMA_NAME}.states s
            ON o.state_id = s.state_id

        {where_clause}

        GROUP BY 1

        ORDER BY 1;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "period": row["period"],
            "for_profit": int(
                row["for_profit"] or 0
            ),
            "non_profit": int(
                row["non_profit"] or 0
            ),
            "total": int(
                row["total"] or 0
            ),
        }
        for row in rows
    ]


def build_dashboard_response(
    cursor,
    filters,
    contributor_available,
):
    return {
        "summary": fetch_summary(
            cursor,
            filters,
            contributor_available,
        ),

        "growth_trend": fetch_growth_trend(
            cursor,
            filters,
        ),

        "organizations_by_location":
            fetch_organizations_by_location(
                cursor,
                filters,
            ),

        "organizations_by_size":
            fetch_organizations_by_size(
                cursor,
                filters,
            ),

        "collaborator_vs_contributor":
            fetch_collaborator_vs_contributor(
                cursor,
                filters,
                contributor_available,
            ),

        "rating_distribution":
            fetch_rating_distribution(
                cursor,
                filters,
            ),

        "organization_type_distribution":
            fetch_organization_type_distribution(
                cursor,
                filters,
            ),
    }


def lambda_handler(event, context):
    conn = None
    cursor = None

    try:
        filters = get_event_body(event)

        valid, error_message = validate_filters(
            filters
        )

        if not valid:
            return build_response(
                400,
                {
                    "error": error_message
                },
            )

        conn = get_db_connection()

        cursor = conn.cursor(
            cursor_factory=RealDictCursor
        )

        contributor_available = (
            check_is_contributor_available(cursor)
        )

        response_body = build_dashboard_response(
            cursor,
            filters,
            contributor_available,
        )

        return build_response(
            200,
            response_body,
        )

    except psycopg2.Error as error:
        print(
            "Organization analytics database error: "
            f"{error}"
        )

        return build_response(
            500,
            {
                "error": "Internal Server Error"
            },
        )

    except Exception as error:
        print(
            "Organization analytics API failed: "
            f"{error}"
        )

        return build_response(
            500,
            {
                "error": "Internal Server Error"
            },
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


if __name__ == "__main__":
    test_event = {
        "time_filter": "ALL",
        "start_date": None,
        "end_date": None,
        "group_by": "monthly",
        "region": "ALL",
        "organization_type": "ALL",
    }

    result = lambda_handler(
        test_event,
        None,
    )

    print(
        "Status:",
        result["statusCode"],
    )

    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2,
        )
    )   