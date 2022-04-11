from typing import Any, Dict, List, OrderedDict

import pandas as pd
from prefect.utilities import logging
from simple_salesforce import Salesforce as SF
from simple_salesforce.exceptions import SalesforceMalformedRequest

from ..config import local_config
from .base import Source

logger = logging.get_logger(__name__)


class Salesforce(Source):
    """
    A class for pulling data from theSalesforce.
    Parameters
    ----------
    """

    def __init__(
        self,
        *args,
        domain: str = "test",
        client_id: str = "viadot",
        credentials: Dict[str, Any] = None,
        env: str = "DEV",
        **kwargs,
    ):
        try:
            DEFAULT_CREDENTIALS = local_config["SALESFORCE"].get(env)
        except KeyError:
            DEFAULT_CREDENTIALS = None

        self.credentials = credentials or DEFAULT_CREDENTIALS or {}

        super().__init__(*args, credentials=self.credentials, **kwargs)

        if env == "DEV":
            self.salesforce = SF(
                username=self.credentials["username"],
                password=self.credentials["password"],
                security_token="",
                domain=domain,
                client_id=client_id,
            )
        elif env == "QA":
            self.salesforce = SF(
                username=self.credentials["username"],
                password=self.credentials["password"],
                security_token=self.credentials["token"],
                domain=domain,
                client_id=client_id,
            )

        else:
            raise ValueError("The only available environments are DEV and QA.")

    def upsert(self, df: pd.DataFrame, table: str, external_id: str = None) -> None:

        if df.empty:
            logger.info("No data to upsert.")
            return

        if external_id and external_id not in df.columns:
            raise ValueError(
                f"Passed DataFrame does not contain column '{external_id}'."
            )

        table_to_upsert = getattr(self.salesforce, table)
        records = df.to_dict("records")
        records_cp = records.copy()

        for record in records_cp:
            if external_id:
                if record[external_id] is None:
                    continue
                else:
                    merge_key = f"{external_id}/{record[external_id]}"
                    record.pop(external_id)
            else:
                merge_key = record["Id"]

            record.pop("Id")

            try:
                response = table_to_upsert.upsert(data=record, record_id=merge_key)
            except SalesforceMalformedRequest as e:
                raise ValueError(f"Upsert of record {merge_key} failed.") from e

            codes = {200: "updated", 201: "created", 204: "updated"}
            logger.info(f"Successfully {codes[response]} record {merge_key}.")

            if response not in list(codes.keys()):
                raise ValueError(
                    f"Upsert failed for record: \n{record} with response {response}"
                )
        logger.info(
            f"Successfully upserted {len(records)} records into table '{table}'."
        )

    def download(
        self, query: str = None, table: str = None, columns: List[str] = None
    ) -> List[OrderedDict]:
        if not query:
            if columns:
                columns_str = ", ".join(columns)
            else:
                columns_str = "FIELDS(STANDARD)"
            query = f"SELECT {columns_str} FROM {table}"
        records = self.salesforce.query(query).get("records")
        # Take trash out.
        _ = [record.pop("attributes") for record in records]
        return records

    def to_df(
        self,
        query: str = None,
        table: str = None,
        columns: List[str] = None,
        if_empty: str = None,
    ) -> pd.DataFrame:
        # TODO: handle if_empty, add typing (should be Literal)
        records = self.download(query=query, table=table, columns=columns)

        if not records:
            raise ValueError(f"Query produced no data.")

        return pd.DataFrame(records)
