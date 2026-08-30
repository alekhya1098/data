import json

import os

import sys

import unittest

from datetime import datetime

from unittest.mock import MagicMock, patch

import psycopg2

sys.path.append(

    os.path.dirname(

        os.path.abspath(__file__)

    )

)

import organization_analytics as analytics

class TestOrganizationAnalytics(unittest.TestCase):

    # ------------------------------------------------------------------

    # Filter validation

    # ------------------------------------------------------------------

    def test_validate_filters_accepts_standard_payload(self):

        filters = {

            "time_filter": "30D",

            "start_date": None,

            "end_date": None,

            "group_by": "daily",

            "region": "ALL",

            "organization_type": "ALL",

        }

        valid, error = analytics.validate_filters(filters)

        self.assertTrue(valid)

        self.assertIsNone(error)

    def test_validate_filters_rejects_invalid_time_filter(self):

        filters = {

            "time_filter": "BAD",

            "group_by": "daily",

            "region": "ALL",

            "organization_type": "ALL",

        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)

        self.assertIn(

            "Invalid time_filter",

            error,

        )

    def test_validate_filters_rejects_invalid_group_by(self):

        filters = {

            "time_filter": "ALL",

            "group_by": "hourly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)

        self.assertIn(

            "Invalid group_by",

            error,

        )

    def test_validate_filters_rejects_invalid_organization_type(self):

        filters = {

            "time_filter": "ALL",

            "group_by": "daily",

            "region": "ALL",

            "organization_type": "government",

        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)

        self.assertIn(

            "Invalid organization_type",

            error,

        )

    def test_custom_filter_requires_both_dates(self):

        filters = {

            "time_filter": "CUSTOM",

            "start_date": "2026-01-01",

            "end_date": None,

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)

        self.assertIn(

            "requires both start_date and end_date",

            error,

        )

    def test_custom_filter_rejects_bad_date_format(self):

        filters = {

            "time_filter": "CUSTOM",

            "start_date": "01-01-2026",

            "end_date": "2026-06-30",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)

        self.assertIn(

            "YYYY-MM-DD",

            error,

        )

    def test_custom_filter_rejects_start_after_end(self):

        filters = {

            "time_filter": "CUSTOM",

            "start_date": "2026-07-01",

            "end_date": "2026-06-30",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)

        self.assertIn(

            "start_date cannot be after end_date",

            error,

        )

    # ------------------------------------------------------------------

    # Filter SQL construction

    # ------------------------------------------------------------------

    def test_build_filters_region(self):

        filters = {

            "time_filter": "ALL",

            "group_by": "monthly",

            "region": "California",

            "organization_type": "ALL",

        }

        where_clause, params = analytics.build_filters(

            filters

        )

        self.assertIn(

            "LOWER(s.state_name) = LOWER(%s)",

            where_clause,

        )

        self.assertEqual(

            params,

            [

                "California",

                "California",

            ],

        )

    def test_build_filters_non_profit(self):

        filters = {

            "time_filter": "ALL",

            "organization_type": "non_profit",

        }

        where_clause, params = analytics.build_filters(

            filters

        )

        self.assertIn(

            "LOWER(REPLACE(o.org_type::text, '-', '_')) = %s",

            where_clause,

        )

        self.assertEqual(

            params,

            ["non_profit"],

        )

    def test_build_filters_for_profit(self):

        filters = {

            "time_filter": "ALL",

            "organization_type": "for_profit",

        }

        where_clause, params = analytics.build_filters(

            filters

        )

        self.assertIn(

            "LOWER(REPLACE(o.org_type::text, '-', '_')) = %s",

            where_clause,

        )

        self.assertEqual(

            params,

            ["for_profit"],

        )

    def test_build_filters_custom_date_range(self):

        filters = {

            "time_filter": "CUSTOM",

            "start_date": "2026-01-01",

            "end_date": "2026-06-30",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        where_clause, params = analytics.build_filters(

            filters

        )

        self.assertIn(

            "o.created_at >= %s",

            where_clause,

        )

        self.assertIn(

            "o.created_at < (%s::date + INTERVAL '1 day')",

            where_clause,

        )

        self.assertEqual(

            params,

            [

                "2026-01-01",

                "2026-06-30",

            ],

        )

    def test_build_filters_can_exclude_time_filter(self):

        filters = {

            "time_filter": "CUSTOM",

            "start_date": "2026-01-01",

            "end_date": "2026-06-30",

            "region": "California",

            "organization_type": "non_profit",

        }

        where_clause, params = analytics.build_filters(

            filters,

            include_time=False,

        )

        self.assertNotIn(

            "o.created_at",

            where_clause,

        )

        self.assertIn(

            "LOWER(s.state_name) = LOWER(%s)",

            where_clause,

        )

        self.assertIn(

            "LOWER(REPLACE(o.org_type::text, '-', '_')) = %s",

            where_clause,

        )

        self.assertEqual(

            params,

            [

                "California",

                "California",

                "non_profit",

            ],

        )

    # ------------------------------------------------------------------

    # Summary

    # ------------------------------------------------------------------

    def test_fetch_summary(self):

        cursor = MagicMock()

        cursor.fetchone.return_value = {

            "total_organizations": 40,

            "total_collaborators": 21,

            "total_contributors": 19,

            "average_org_rating": 3.23,

        }

        filters = {

            "time_filter": "ALL",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = analytics.fetch_summary(

            cursor,

            filters,

            True,

        )

        self.assertEqual(

            result["total_organizations"],

            40,

        )

        self.assertEqual(

            result["total_collaborators"],

            21,

        )

        self.assertEqual(

            result["total_contributors"],

            19,

        )

        self.assertEqual(

            result["average_org_rating"],

            3.23,

        )

        cursor.execute.assert_called_once()

    def test_fetch_summary_handles_null_rating(self):

        cursor = MagicMock()

        cursor.fetchone.return_value = {

            "total_organizations": 0,

            "total_collaborators": 0,

            "total_contributors": 0,

            "average_org_rating": None,

        }

        filters = {

            "time_filter": "ALL",

            "group_by": "daily",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = analytics.fetch_summary(

            cursor,

            filters,

            True,

        )

        self.assertEqual(

            result["average_org_rating"],

            0,

        )

    def test_fetch_summary_when_contributor_column_missing(self):

        cursor = MagicMock()

        cursor.fetchone.return_value = {

            "total_organizations": 10,

            "total_collaborators": 4,

            "total_contributors": 0,

            "average_org_rating": 4.0,

        }

        filters = {

            "time_filter": "ALL",

            "group_by": "daily",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = analytics.fetch_summary(

            cursor,

            filters,

            False,

        )

        self.assertEqual(

            result["total_contributors"],

            0,

        )

    # ------------------------------------------------------------------

    # Growth trend

    # ------------------------------------------------------------------

    def test_growth_trend_empty_result(self):

        cursor = MagicMock()

        cursor.fetchall.return_value = []

        filters = {

            "time_filter": "ALL",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = analytics.fetch_growth_trend(

            cursor,

            filters,

        )

        self.assertEqual(

            result,

            [],

        )

    def test_growth_trend_all_returns_cumulative_values(self):

        cursor = MagicMock()

        cursor.fetchall.return_value = [

            {

                "period": datetime(2025, 1, 1),

                "total_organizations": 10,

                "total_collaborators": 4,

            },

            {

                "period": datetime(2025, 2, 1),

                "total_organizations": 15,

                "total_collaborators": 7,

            },

        ]

        filters = {

            "time_filter": "ALL",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = analytics.fetch_growth_trend(

            cursor,

            filters,

        )

        self.assertEqual(

            result[0]["total_organizations"],

            10,

        )

        self.assertEqual(

            result[1]["total_organizations"],

            15,

        )

        self.assertEqual(

            result[1]["total_collaborators"],

            7,

        )

    def test_growth_trend_custom_preserves_baseline(self):

        cursor = MagicMock()

        cursor.fetchall.return_value = [

            {

                "period": datetime(2025, 8, 1),

                "total_organizations": 29,

                "total_collaborators": 16,

            },

            {

                "period": datetime(2025, 9, 1),

                "total_organizations": 32,

                "total_collaborators": 18,

            },

        ]

        filters = {

            "time_filter": "CUSTOM",

            "start_date": "2025-08-01",

            "end_date": "2025-12-31",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = analytics.fetch_growth_trend(

            cursor,

            filters,

        )

        self.assertEqual(

            result[0]["total_organizations"],

            29,

        )

        self.assertEqual(

            result[0]["total_collaborators"],

            16,

        )

        self.assertEqual(

            result[1]["total_organizations"],

            32,

        )

        sql = cursor.execute.call_args[0][0]

        self.assertIn(

            "WITH baseline AS",

            sql,

        )

        self.assertIn(

            "organizations_before",

            sql,

        )

    # ------------------------------------------------------------------

    # Location

    # ------------------------------------------------------------------

    def test_location_empty_result(self):

        cursor = MagicMock()

        cursor.fetchall.side_effect = [

            [],

            [],

        ]

        filters = {

            "time_filter": "ALL",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = analytics.fetch_organizations_by_location(

            cursor,

            filters,

        )

        self.assertEqual(

            result,

            {

                "by_state": [],

                "by_city": [],

            },

        )

        self.assertEqual(

            cursor.execute.call_count,

            2,

        )

    def test_location_returns_state_and_city_separately(self):

        cursor = MagicMock()

        cursor.fetchall.side_effect = [

            [

                {

                    "state_id": "TX",

                    "state_name": "Texas",

                    "organization_count": 3,

                    "percentage": 7.5,

                },

                {

                    "state_id": "CA",

                    "state_name": "California",

                    "organization_count": 1,

                    "percentage": 2.5,

                },

            ],

            [

                {

                    "city_name": "Hortonberg",

                    "state_id": "TX",

                    "state_name": "Texas",

                    "organization_count": 1,

                    "percentage": 2.5,

                },

            ],

        ]

        filters = {

            "time_filter": "ALL",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = analytics.fetch_organizations_by_location(

            cursor,

            filters,

        )

        self.assertEqual(

            result["by_state"][0]["state_id"],

            "TX",

        )

        self.assertEqual(

            result["by_state"][0]["organization_count"],

            3,

        )

        self.assertEqual(

            result["by_city"][0]["city_name"],

            "Hortonberg",

        )

        self.assertEqual(

            cursor.execute.call_count,

            2,

        )

    # ------------------------------------------------------------------

    # Collaborator / Contributor

    # ------------------------------------------------------------------

    def test_collaborator_vs_contributor_percentages(self):

        cursor = MagicMock()

        cursor.fetchone.return_value = {

            "collaborator_only_count": 21,

            "contributor_only_count": 19,

            "both_count": 0,

            "neither_count": 0,

        }

        filters = {

            "time_filter": "ALL",

            "group_by": "daily",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = (

            analytics.fetch_collaborator_vs_contributor(

                cursor,

                filters,

                True,

            )

        )

        self.assertEqual(

            result,

            [

                {

                    "type": "collaborator_only",

                    "organization_count": 21,

                    "percentage": 52.5,

                },

                {

                    "type": "contributor_only",

                    "organization_count": 19,

                    "percentage": 47.5,

                },

                {

                    "type": "both",

                    "organization_count": 0,

                    "percentage": 0.0,

                },

                {

                    "type": "neither",

                    "organization_count": 0,

                    "percentage": 0.0,

                },

            ],

        )

    def test_collaborator_vs_contributor_supports_overlap(self):

        cursor = MagicMock()

        cursor.fetchone.return_value = {

            "collaborator_only_count": 15,

            "contributor_only_count": 10,

            "both_count": 5,

            "neither_count": 10,

        }

        filters = {

            "time_filter": "ALL",

            "group_by": "daily",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = (

            analytics.fetch_collaborator_vs_contributor(

                cursor,

                filters,

                True,

            )

        )

        self.assertEqual(

            result[0]["percentage"],

            37.5,

        )

        self.assertEqual(

            result[1]["percentage"],

            25.0,

        )

        self.assertEqual(

            result[2]["percentage"],

            12.5,

        )

        self.assertEqual(

            result[3]["percentage"],

            25.0,

        )

    def test_collaborator_vs_contributor_empty_result(self):

        cursor = MagicMock()

        cursor.fetchone.return_value = {

            "collaborator_only_count": 0,

            "contributor_only_count": 0,

            "both_count": 0,

            "neither_count": 0,

        }

        filters = {

            "time_filter": "ALL",

            "group_by": "daily",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = (

            analytics.fetch_collaborator_vs_contributor(

                cursor,

                filters,

                True,

            )

        )

        self.assertEqual(

            result,

            [

                {

                    "type": "collaborator_only",

                    "organization_count": 0,

                    "percentage": 0,

                },

                {

                    "type": "contributor_only",

                    "organization_count": 0,

                    "percentage": 0,

                },

                {

                    "type": "both",

                    "organization_count": 0,

                    "percentage": 0,

                },

                {

                    "type": "neither",

                    "organization_count": 0,

                    "percentage": 0,

                },

            ],

        )

    def test_collaborator_distribution_when_contributor_missing(self):

        cursor = MagicMock()

        cursor.fetchone.return_value = {

            "collaborator_count": 6,

            "non_collaborator_count": 4,

        }

        filters = {

            "time_filter": "ALL",

            "group_by": "daily",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = (

            analytics.fetch_collaborator_vs_contributor(

                cursor,

                filters,

                False,

            )

        )

        self.assertEqual(

            result[0]["type"],

            "collaborator",

        )

        self.assertEqual(

            result[0]["percentage"],

            60.0,

        )

        self.assertEqual(

            result[1]["type"],

            "non_collaborator",

        )

        self.assertEqual(

            result[1]["percentage"],

            40.0,

        )

    # ------------------------------------------------------------------

    # Rating

    # ------------------------------------------------------------------

    def test_rating_distribution_returns_one_to_five(self):

        cursor = MagicMock()

        cursor.fetchall.return_value = [

            {

                "rating": 1,

                "organization_count": 0,

            },

            {

                "rating": 2,

                "organization_count": 2,

            },

            {

                "rating": 3,

                "organization_count": 5,

            },

            {

                "rating": 4,

                "organization_count": 7,

            },

            {

                "rating": 5,

                "organization_count": 10,

            },

        ]

        filters = {

            "time_filter": "ALL",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = analytics.fetch_rating_distribution(

            cursor,

            filters,

        )

        self.assertEqual(

            len(result),

            5,

        )

        self.assertEqual(

            [item["rating"] for item in result],

            [1, 2, 3, 4, 5],

        )

    # ------------------------------------------------------------------

    # Organization type distribution

    # ------------------------------------------------------------------

    def test_organization_type_distribution(self):

        cursor = MagicMock()

        cursor.fetchall.return_value = [

            {

                "period": datetime(2026, 1, 1),

                "for_profit": 3,

                "non_profit": 5,

                "total": 8,

            }

        ]

        filters = {

            "time_filter": "ALL",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        result = (

            analytics.fetch_organization_type_distribution(

                cursor,

                filters,

            )

        )

        self.assertEqual(

            result[0]["for_profit"],

            3,

        )

        self.assertEqual(

            result[0]["non_profit"],

            5,

        )

        self.assertEqual(

            result[0]["total"],

            8,

        )

        sql = cursor.execute.call_args[0][0]

        self.assertIn(

            "REPLACE(o.org_type::text, '-', '_')",

            sql,

        )

    # ------------------------------------------------------------------

    # Response structure

    # ------------------------------------------------------------------

    def test_response_structure(self):

        cursor = MagicMock()

        with patch.object(

            analytics,

            "fetch_summary",

            return_value={

                "total_organizations": 40,

                "total_collaborators": 21,

                "total_contributors": 19,

                "average_org_rating": 3.23,

            },

        ), patch.object(

            analytics,

            "fetch_growth_trend",

            return_value=[],

        ), patch.object(

            analytics,

            "fetch_organizations_by_location",

            return_value={

                "by_state": [],

                "by_city": [],

            },

        ), patch.object(

            analytics,

            "fetch_organizations_by_size",

            return_value=[],

        ), patch.object(

            analytics,

            "fetch_collaborator_vs_contributor",

            return_value=[],

        ), patch.object(

            analytics,

            "fetch_rating_distribution",

            return_value=[],

        ), patch.object(

            analytics,

            "fetch_organization_type_distribution",

            return_value=[],

        ):

            result = analytics.build_dashboard_response(

                cursor,

                {},

                True,

            )

        self.assertEqual(

            set(result.keys()),

            {

                "summary",

                "growth_trend",

                "organizations_by_location",

                "organizations_by_size",

                "collaborator_vs_contributor",

                "rating_distribution",

                "organization_type_distribution",

            },

        )

        self.assertEqual(

            result["organizations_by_location"],

            {

                "by_state": [],

                "by_city": [],

            },

        )

    # ------------------------------------------------------------------

    # Lambda handler

    # ------------------------------------------------------------------

    @patch.object(

        analytics,

        "get_db_connection",

    )

    def test_lambda_handler_success(

        self,

        mock_get_db_connection,

    ):

        mock_conn = MagicMock()

        mock_cursor = MagicMock()

        mock_conn.cursor.return_value = mock_cursor

        mock_get_db_connection.return_value = mock_conn

        with patch.object(

            analytics,

            "check_is_contributor_available",

            return_value=True,

        ), patch.object(

            analytics,

            "build_dashboard_response",

            return_value=analytics.get_default_response(),

        ):

            event = {

                "time_filter": "ALL",

                "group_by": "monthly",

                "region": "ALL",

                "organization_type": "ALL",

            }

            response = analytics.lambda_handler(

                event,

                None,

            )

        self.assertEqual(

            response["statusCode"],

            200,

        )

        body = json.loads(

            response["body"]

        )

        self.assertIn(

            "summary",

            body,

        )

        self.assertIn(

            "growth_trend",

            body,

        )

        self.assertIn(

            "organizations_by_location",

            body,

        )

        mock_cursor.close.assert_called_once()

        mock_conn.close.assert_called_once()

    def test_lambda_handler_invalid_filter(self):

        event = {

            "time_filter": "INVALID",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        response = analytics.lambda_handler(

            event,

            None,

        )

        self.assertEqual(

            response["statusCode"],

            400,

        )

        body = json.loads(

            response["body"]

        )

        self.assertIn(

            "error",

            body,

        )

    def test_lambda_handler_custom_missing_end_date(self):

        event = {

            "time_filter": "CUSTOM",

            "start_date": "2026-01-01",

            "end_date": None,

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        response = analytics.lambda_handler(

            event,

            None,

        )

        self.assertEqual(

            response["statusCode"],

            400,

        )

    @patch.object(

        analytics,

        "get_db_connection",

    )

    def test_lambda_handler_database_exception(

        self,

        mock_get_db_connection,

    ):

        mock_get_db_connection.side_effect = (

            psycopg2.OperationalError(

                "database unavailable"

            )

        )

        event = {

            "time_filter": "ALL",

            "group_by": "monthly",

            "region": "ALL",

            "organization_type": "ALL",

        }

        response = analytics.lambda_handler(

            event,

            None,

        )

        self.assertEqual(

            response["statusCode"],

            500,

        )

        body = json.loads(

            response["body"]

        )

        self.assertEqual(

            body["error"],

            "Internal Server Error",

        )

    @patch.object(

        analytics,

        "get_db_connection",

    )

    def test_lambda_handler_query_exception(

        self,

        mock_get_db_connection,

    ):

        mock_conn = MagicMock()

        mock_cursor = MagicMock()

        mock_conn.cursor.return_value = mock_cursor

        mock_get_db_connection.return_value = mock_conn

        with patch.object(

            analytics,

            "check_is_contributor_available",

            side_effect=psycopg2.DatabaseError(

                "query failed"

            ),

        ):

            event = {

                "time_filter": "ALL",

                "group_by": "monthly",

                "region": "ALL",

                "organization_type": "ALL",

            }

            response = analytics.lambda_handler(

                event,

                None,

            )

        self.assertEqual(

            response["statusCode"],

            500,

        )

        mock_cursor.close.assert_called_once()

        mock_conn.close.assert_called_once()

if __name__ == "__main__":

    unittest.main(

        verbosity=2

    )