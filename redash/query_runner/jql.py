import re
from collections import OrderedDict

from redash.query_runner import *
from redash.utils import json_dumps, json_loads


# TODO: make this more general and move into __init__.py
class ResultSet(object):
    def __init__(self):
        self.columns = OrderedDict()
        self.rows = []

    def add_row(self, row):
        for key in row.keys():
            self.add_column(key)

        self.rows.append(row)

    def add_column(self, column, column_type=TYPE_STRING):
        if column not in self.columns:
            self.columns[column] = {
                "name": column,
                "type": column_type,
                "friendly_name": column,
            }

    def to_json(self):
        return json_dumps({"rows": self.rows, "columns": list(self.columns.values())})

    def merge(self, set):
        self.rows = self.rows + set.rows


def parse_issue(issue, field_mapping):
    result = OrderedDict()
    result["key"] = issue["key"]

    for k, v in issue["fields"].items():  #
        output_name = field_mapping.get_output_field_name(k)
        member_names = field_mapping.get_dict_members(k)

        if isinstance(v, dict):
            if len(member_names) > 0:
                # if field mapping with dict member mappings defined get value of each member
                for member_name in member_names:
                    if member_name in v:
                        result[
                            field_mapping.get_dict_output_field_name(k, member_name)
                        ] = v[member_name]

            else:
                # these special mapping rules are kept for backwards compatibility
                if "key" in v:
                    result[f"{output_name}_key"] = v["key"]
                if "name" in v:
                    result[f"{output_name}_name"] = v["name"]

                if k in v:
                    result[output_name] = v[k]

                if "watchCount" in v:
                    result[output_name] = v["watchCount"]

        elif isinstance(v, list):
            if len(member_names) > 0:
                # if field mapping with dict member mappings defined get value of each member
                for member_name in member_names:
                    listValues = []
                    for listItem in v:
                        if isinstance(listItem, dict):
                            if member_name in listItem:
                                listValues.append(listItem[member_name])
                    if listValues:
                        result[
                            field_mapping.get_dict_output_field_name(k, member_name)
                        ] = ",".join(listValues)

            elif listValues := [
                listItem for listItem in v if not isinstance(listItem, dict)
            ]:
                result[output_name] = ",".join(listValues)

        else:
            result[output_name] = v

    return result


def parse_issues(data, field_mapping):
    results = ResultSet()

    for issue in data["issues"]:
        results.add_row(parse_issue(issue, field_mapping))

    return results


def parse_count(data):
    results = ResultSet()
    results.add_row({"count": data["total"]})
    return results


class FieldMapping:
    def __init__(self, query_field_mapping):
        self.mapping = []
        for k, v in query_field_mapping.items():
            field_name = k
            member_name = None

            if member_parser := re.search("(\w+)\.(\w+)", field_name):
                field_name = member_parser.group(1)
                member_name = member_parser.group(2)

            self.mapping.append(
                {
                    "field_name": field_name,
                    "member_name": member_name,
                    "output_field_name": v,
                }
            )

    def get_output_field_name(self, field_name):
        return next(
            (
                item["output_field_name"]
                for item in self.mapping
                if item["field_name"] == field_name and not item["member_name"]
            ),
            field_name,
        )

    def get_dict_members(self, field_name):
        return [
            item["member_name"]
            for item in self.mapping
            if item["field_name"] == field_name and item["member_name"]
        ]

    def get_dict_output_field_name(self, field_name, member_name):
        return next(
            (
                item["output_field_name"]
                for item in self.mapping
                if item["field_name"] == field_name
                and item["member_name"] == member_name
            ),
            None,
        )


class JiraJQL(BaseHTTPQueryRunner):
    noop_query = '{"queryType": "count"}'
    response_error = "JIRA returned unexpected status code"
    requires_authentication = True
    url_title = "JIRA URL"
    username_title = "Username"
    password_title = "API Token"

    @classmethod
    def name(cls):
        return "JIRA (JQL)"

    def __init__(self, configuration):
        super(JiraJQL, self).__init__(configuration)
        self.syntax = "json"

    def run_query(self, query, user):
        jql_url = f'{self.configuration["url"]}/rest/api/2/search'

        query = json_loads(query)
        query_type = query.pop("queryType", "select")
        field_mapping = FieldMapping(query.pop("fieldMapping", {}))

        if query_type == "count":
            query["maxResults"] = 1
            query["fields"] = ""
        else:
            query["maxResults"] = query.get("maxResults", 1000)

        response, error = self.get_response(jql_url, params=query)
        if error is not None:
            return None, error

        data = response.json()

        if query_type == "count":
            results = parse_count(data)
        else:
            results = parse_issues(data, field_mapping)
            index = data["startAt"] + data["maxResults"]

            while data["total"] > index:
                query["startAt"] = index
                response, error = self.get_response(jql_url, params=query)
                if error is not None:
                    return None, error

                data = response.json()
                index = data["startAt"] + data["maxResults"]

                addl_results = parse_issues(data, field_mapping)
                results.merge(addl_results)

        return results.to_json(), None


register(JiraJQL)
