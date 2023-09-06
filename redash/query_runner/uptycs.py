from redash.query_runner import *
from redash.utils import json_dumps, json_loads

import jwt
import datetime
import requests
import logging

logger = logging.getLogger(__name__)


class Uptycs(BaseSQLQueryRunner):
    should_annotate_query = False
    noop_query = "SELECT 1"

    @classmethod
    def configuration_schema(cls):
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "customer_id": {"type": "string"},
                "key": {"type": "string"},
                "verify_ssl": {
                    "type": "boolean",
                    "default": True,
                    "title": "Verify SSL Certificates",
                },
                "secret": {"type": "string"},
            },
            "order": ["url", "customer_id", "key", "secret"],
            "required": ["url", "customer_id", "key", "secret"],
            "secret": ["secret", "key"],
        }

    def generate_header(self, key, secret):
        utcnow = datetime.datetime.utcnow()
        date = utcnow.strftime("%a, %d %b %Y %H:%M:%S GMT")
        auth_var = jwt.encode({"iss": key}, secret, algorithm="HS256")
        authorization = f"Bearer {auth_var}"
        return {"date": date, "Authorization": authorization}

    def transformed_to_redash_json(self, data):
        transformed_columns = []
        # convert all type to JSON string
        # In future we correct data type  mapping later
        if "columns" in data:
            for json_each in data["columns"]:
                name = json_each["name"]
                new_json = {"name": name, "type": "string", "friendly_name": name}
                transformed_columns.append(new_json)
        rows = data["items"] if "items" in data else []
        return {"columns": transformed_columns, "rows": rows}

    def api_call(self, sql):
        # JWT encoded header
        header = self.generate_header(
            self.configuration.get("key"), self.configuration.get("secret")
        )

        # URL form using API key file based on GLOBAL
        url = f'{self.configuration.get("url")}/public/api/customers/{self.configuration.get("customer_id")}/query'

        # post data base sql
        post_data_json = {"query": sql}

        response = requests.post(
            url,
            headers=header,
            json=post_data_json,
            verify=self.configuration.get("verify_ssl", True),
        )

        if response.status_code == 200:
            response_output = json_loads(response.content)
        else:
            error = f"status_code {response.status_code}" + "\n"
            error = f"{error}failed to connect"
            json_data = {}
            return json_data, error
        # if we get right status code then call transfored_to_redash
        json_data = self.transformed_to_redash_json(response_output)
        error = None
        # if we got error from Uptycs include error information
        if "error" in response_output:
            error = response_output["error"]["message"]["brief"]
            error = error + "\n" + response_output["error"]["message"]["detail"]
        return json_data, error

    def run_query(self, query, user):
        data, error = self.api_call(query)
        json_data = json_dumps(data)
        logger.debug("%s", json_data)
        return json_data, error

    def get_schema(self, get_stats=False):
        header = self.generate_header(
            self.configuration.get("key"), self.configuration.get("secret")
        )
        url = f'{self.configuration.get("url")}/public/api/customers/{self.configuration.get("customer_id")}/schema/global'
        response = requests.get(
            url, headers=header, verify=self.configuration.get("verify_ssl", True)
        )
        redash_json = []
        schema = json_loads(response.content)
        for each_def in schema["tables"]:
            table_name = each_def["name"]
            columns = [col["name"] for col in each_def["columns"]]
            table_json = {"name": table_name, "columns": columns}
            redash_json.append(table_json)

        logger.debug("%s", list(schema.values()))
        return redash_json


register(Uptycs)
