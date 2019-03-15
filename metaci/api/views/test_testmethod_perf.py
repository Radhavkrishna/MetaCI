from urllib.parse import urlencode
import random
from datetime import timedelta, datetime
from django.utils import timezone

from rest_framework.test import APIClient, APITestCase

import factory
import factory.fuzzy

from metaci.plan.models import Plan, PlanRepository
from metaci.testresults.models import TestResult, TestMethod, TestClass
from metaci.build.models import BuildFlow, Build
from metaci.repository.models import Branch, Repository

from metaci.users.models import User


class PlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Plan


class RepositoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Repository

    github_id = 1234


class PlanRepositoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PlanRepository

    plan = factory.SubFactory(PlanFactory)
    repo = factory.SubFactory(RepositoryFactory)


class Branch(factory.django.DjangoModelFactory):
    class Meta:
        model = Branch


class BuildFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Build

    plan = factory.SubFactory(PlanFactory)
    repo = factory.SubFactory(RepositoryFactory)


class BuildFlowFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BuildFlow

    tests_total = 5
    build = factory.SubFactory(BuildFactory)
    flow = "rida"


class TestClassFactory(factory.django.DjangoModelFactory):
    __test__ = False  # PyTest is confused by the classname

    class Meta:
        model = TestClass

    repo = factory.SubFactory(RepositoryFactory)


class TestMethodFactory(factory.django.DjangoModelFactory):
    __test__ = False  # PyTest is confused by the classname

    class Meta:
        model = TestMethod

    testclass = factory.SubFactory(TestClassFactory)
    name = "GenericMethod"


class TestResultFactory(factory.django.DjangoModelFactory):
    __test__ = False  # PyTest is confused by the classname

    class Meta:
        model = TestResult

    build_flow = factory.SubFactory(BuildFlowFactory)
    method = factory.SubFactory(TestMethodFactory)
    duration = 5


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    email = factory.Sequence("user_{}@example.com".format)
    username = factory.Sequence("user_{}@example.com".format)
    password = factory.PostGenerationMethodCall("set_password", "foobar")
    # socialaccount_set = factory.RelatedFactory(SocialAccountFactory, "user")


class StaffSuperuserFactory(UserFactory):
    is_staff = True
    is_superuser = True


class _TestingHelpers:
    def debugmsg(self, *args):
        print(*args)

    @classmethod
    def make_user_and_client(cls):
        user = StaffSuperuserFactory()
        client = APIClient()
        client.force_authenticate(user)
        response = client.get("/api/")
        if response.status_code == 400 and "DisallowedHost" in str(response.content):
            cls.debugmsg("**** YOU MAY NEED TO ADD AN ALLOWED_HOSTS TO YOUR TEST.PY")
            raise (Exception(response))

        assert response.status_code == 200, response.content
        return client, user

    def api_url(self, **kwargs):
        params = urlencode(kwargs, True)
        self.debugmsg("QueryParams", params)
        return r"/api/testmethod_perf/?" + params

    def find_by(self, fieldname, objs, value):
        if type(objs) == dict:
            objs = objs.get("results", objs)
        return next((x for x in objs if x[fieldname] == value), None)

    def api_call_helper(self, **kwargs):
        self.debugmsg("Request", kwargs)
        response = self.client.get(self.api_url(**kwargs, format="api"))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(self.api_url(**kwargs))
        self.assertEqual(response.status_code, 200)
        objs = response.json()
        self.debugmsg("Response", objs)
        return objs["results"]

    def stats_test_helper(self, stat):
        return self.api_call_helper(include_fields=stat)

    def identical_tests_helper(self, count, method_name="GenericMethod", **fields):
        t1 = TestResultFactory(
            build_flow__tests_total=1, method__name=method_name, **fields
        )
        for i in range(count - 1):
            TestResultFactory(**fields, build_flow__tests_total=1, method=t1.method)


class TestTestMethodPerfRESTAPI(APITestCase, _TestingHelpers):
    """Test the testmethodperf REST API"""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.user = cls.make_user_and_client()
        super().setUpClass()

    def setUp(self):
        self.client.force_authenticate(self.user)
        t1 = TestResultFactory(
            method__name="Foo", duration=10, build_flow__tests_total=1
        )
        TestResultFactory(duration=2, build_flow__tests_total=1, method=t1.method)
        TestResultFactory(method__name="Bar", duration=3, build_flow__tests_total=1)
        TestResultFactory(method__name="Bar", duration=5, build_flow__tests_total=1)

    def test_counting(self):
        """Test counting of method invocations"""
        objs = self.stats_test_helper("count")
        self.assertEqual(self.find_by("method_name", objs, "Foo")["count"], 2)
        self.assertEqual(self.find_by("method_name", objs, "Bar")["count"], 2)

    def test_averaging(self):
        """Test averaging of methods"""
        objs = self.stats_test_helper("duration_average")

        self.assertEqual(
            self.find_by("method_name", objs, "Foo")["duration_average"], 6
        )
        self.assertEqual(
            self.find_by("method_name", objs, "Bar")["duration_average"], 4
        )

    def test_all_included_fields(self):
        includable_fields = [
            "duration_average",
            "duration_slow",
            "duration_fast",
            "duration_stddev",
            "duration_coefficient_var",
            "cpu_usage_average",
            "cpu_usage_low",
            "cpu_usage_high",
            "count",
            "failures",
            "assertion_failures",
            "DML_failures",
            "Other_failures",
            "success_percentage",
        ]

        def _test_fields(fields):
            response = self.client.get(self.api_url(include_fields=fields))
            self.assertEqual(response.status_code, 200)
            rows = response.json()["results"]
            for field in fields:
                for row in rows:
                    self.assertIn(field, row.keys())

        random.seed("xyzzy")
        for i in range(10):
            field = random.sample(includable_fields, 1)
            _test_fields(field)

        for i in range(10):
            field1, field2 = random.sample(includable_fields, 2)
            _test_fields([field1, field2])

        for i in range(10):
            field1, field2, field3 = random.sample(includable_fields, 3)
            _test_fields([field1, field2, field3])

        _test_fields(includable_fields)

    def test_duration_slow(self):
        """Test counting high durations"""

        self.identical_tests_helper(method_name="Foo", count=20, duration=10)
        _outlier = TestResultFactory(method__name="Foo", duration=11)  # noqa
        rows = self.api_call_helper(include_fields=["duration_slow", "count"])

        self.assertEqual(self.find_by("method_name", rows, "Foo")["duration_slow"], 10)

    def test_duration_fast(self):
        """Test counting high durations"""

        self.identical_tests_helper(method_name="Foo", count=20, duration=2)
        _outlier = TestResultFactory(method__name="Foo", duration=1)  # noqa
        rows = self.api_call_helper(include_fields=["duration_slow", "count"])

        self.assertEqual(self.find_by("method_name", rows, "Foo")["duration_slow"], 2)

    def test_count_failures(self):
        """Test counting failed tests"""
        self.identical_tests_helper(method_name="FailingTest", count=15, outcome="Fail")
        self.identical_tests_helper(method_name="FailingTest", count=10, outcome="Pass")
        rows = self.api_call_helper(include_fields=["failures", "success_percentage"])

        self.assertEqual(
            self.find_by("method_name", rows, "FailingTest")["failures"], 15
        )
        self.assertEqual(
            self.find_by("method_name", rows, "FailingTest")["success_percentage"],
            10 / 25,
        )

    def test_split_by_repo(self):
        """Test Splitting on repo"""
        self.identical_tests_helper(
            method_name="HedaTest", count=15, build_flow__build__repo__name="HEDA"
        )
        self.identical_tests_helper(
            method_name="NPSPTest", count=20, build_flow__build__repo__name="Cumulus"
        )
        rows = self.api_call_helper(include_fields="count", group_by="repo")

        self.assertEqual(self.find_by("method_name", rows, "HedaTest")["count"], 15)
        self.assertEqual(self.find_by("method_name", rows, "HedaTest")["repo"], "HEDA")
        self.assertEqual(self.find_by("method_name", rows, "NPSPTest")["count"], 20)
        self.assertEqual(
            self.find_by("method_name", rows, "NPSPTest")["repo"], "Cumulus"
        )

    def test_split_by_flow(self):
        """Test splitting on flow"""
        self.identical_tests_helper(
            method_name="HedaTest", count=15, build_flow__flow="ci_feature"
        )
        self.identical_tests_helper(
            method_name="HedaTest", count=20, build_flow__flow="ci_beta"
        )
        rows = self.api_call_helper(include_fields="count", group_by="flow")

        for row in rows:
            self.assertIn(row["flow"], ["ci_feature", "ci_beta", "rida"])

        self.assertEqual(self.find_by("flow", rows, "ci_feature")["count"], 15)
        self.assertEqual(self.find_by("flow", rows, "ci_beta")["count"], 20)

    def test_split_by_flow_ignoring_repo(self):
        """Test splitting on flow regardless of repro"""
        self.identical_tests_helper(
            count=3, build_flow__build__repo__name="HEDA", build_flow__flow="Flow1"
        )
        self.identical_tests_helper(
            count=5, build_flow__build__repo__name="HEDA", build_flow__flow="Flow2"
        )
        self.identical_tests_helper(
            count=7, build_flow__build__repo__name="Cumulus", build_flow__flow="Flow1"
        )
        self.identical_tests_helper(
            count=9, build_flow__build__repo__name="Cumulus", build_flow__flow="Flow2"
        )
        rows = self.api_call_helper(include_fields="count", group_by=["flow"])

        self.assertEqual(self.find_by("flow", rows, "Flow1")["count"], 10)
        self.assertEqual(self.find_by("flow", rows, "Flow2")["count"], 14)

    def test_split_by_plan(self):
        """Test splitting on plan regardless of the rest"""
        self.identical_tests_helper(
            count=3,
            build_flow__build__repo__name="HEDA",
            build_flow__build__plan__name="plan1",
        )
        self.identical_tests_helper(
            count=5,
            build_flow__build__repo__name="HEDA",
            build_flow__build__plan__name="plan2",
        )
        self.identical_tests_helper(
            count=7,
            build_flow__build__repo__name="Cumulus",
            build_flow__build__plan__name="plan1",
        )
        self.identical_tests_helper(
            count=9,
            build_flow__build__repo__name="Cumulus",
            build_flow__build__plan__name="plan2",
        )
        rows = self.api_call_helper(include_fields="count", group_by=["plan"])

        self.assertEqual(self.find_by("plan", rows, "plan1")["count"], 10)
        self.assertEqual(self.find_by("plan", rows, "plan2")["count"], 14)

    def test_order_by_count_desc(self):
        """Test ordering by count"""
        TestResultFactory(method__name="Bar", duration=3, build_flow__tests_total=1)

        rows = self.api_call_helper(o="-count")

        self.assertEqual(rows[0]["method_name"], "Bar")
        self.assertEqual(rows[1]["method_name"], "Foo")

    def test_order_by_count_asc(self):
        """Test ordering by count"""
        TestResultFactory(method__name="Bar", duration=3, build_flow__tests_total=1)

        rows = self.api_call_helper(o="count")

        self.assertEqual(rows[0]["method_name"], "Foo")
        self.assertEqual(rows[1]["method_name"], "Bar")

    def test_order_by_method_name_asc(self):
        rows = self.api_call_helper(o="method_name")
        self.assertTrue(rows[0]["method_name"] < rows[-1]["method_name"])

    def test_order_by_method_name_desc(self):
        rows = self.api_call_helper(o="-method_name")
        self.assertTrue(rows[0]["method_name"] > rows[-1]["method_name"])

    def test_order_by_success_percentage(self):
        TestResultFactory(method__name="Bar", outcome="Pass", build_flow__tests_total=1)
        rows = self.api_call_helper(o="success_percentage")
        self.assertTrue(rows[0]["success_percentage"] < rows[-1]["success_percentage"])

    def test_order_by_success_percentage_desc(self):
        TestResultFactory(method__name="Bar", outcome="Pass", build_flow__tests_total=1)
        rows = self.api_call_helper(o="-success_percentage")
        self.assertTrue(rows[0]["success_percentage"] > rows[-1]["success_percentage"])

    def test_order_by_unknown_field(self):
        response = self.client.get(self.api_url(o="fjioesjfoi"))
        self.assertEqual(response.status_code, 400)
        response.json()  # should still be able to parse it

    def test_include_unknown_field(self):
        response = self.client.get(self.api_url(include_fields=["fjioesjfofi"]))
        self.assertEqual(response.status_code, 400)
        response.json()  # should still be able to parse it

    def test_group_by_unknown_field(self):
        response = self.client.get(self.api_url(include_fields=["fesafs"]))
        self.assertEqual(response.status_code, 400)
        response.json()  # should still be able to parse it

    def test_cannot_specify_two_kinds_of_dates(self):
        response = self.client.get(
            self.api_url(recentdate="today", daterange_after="2019-03-07")
        )
        self.assertEqual(response.status_code, 400)
        response.json()  # should still be able to parse it

    def make_date(self, strdate):
        return timezone.make_aware(datetime.strptime(strdate, r"%Y-%m-%d"))

    def test_filter_by_before_and_after_date(self):
        d = self.make_date
        TestResultFactory(method__name="Bar1", build_flow__time_end=d("2018-03-08"))
        TestResultFactory(method__name="Bar2", build_flow__time_end=d("2018-04-08"))
        TestResultFactory(method__name="Bar3", build_flow__time_end=d("2018-05-08"))
        TestResultFactory(method__name="Bar4", build_flow__time_end=d("2018-06-08"))
        rows = self.api_call_helper(
            daterange_after="2018-04-01", daterange_before="2018-06-01"
        )
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn(row["method_name"], ["Bar2", "Bar3"])
            self.assertNotIn(row["method_name"], ["Bar1", "Bar4"])

    def test_filter_by_recent_date(self):
        yesterday = timezone.make_aware(datetime.today() - timedelta(1))
        day_before = timezone.make_aware(datetime.today() - timedelta(2))
        long_ago = timezone.make_aware(datetime.today() - timedelta(10))
        long_long_ago = timezone.make_aware(datetime.today() - timedelta(12))

        TestResultFactory(method__name="Bar1", build_flow__time_end=yesterday)
        TestResultFactory(method__name="Bar2", build_flow__time_end=day_before)
        TestResultFactory(method__name="Bar3", build_flow__time_end=long_ago)
        TestResultFactory(method__name="Bar4", build_flow__time_end=long_long_ago)
        rows = self.api_call_helper(recentdate="week")
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn(row["method_name"], ["Bar1", "Bar2"])

    def test_api_view(self):
        response = self.client.get(self.api_url(format="api"))
        self.debugmsg(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["content-type"])
