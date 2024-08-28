"""SAP BW API connector."""

import textwrap

import pandas as pd
import pyrfc
from pydantic import BaseModel

from viadot.config import get_source_credentials
from viadot.exceptions import CredentialError, ValidationError
from viadot.sources.base import Source
from viadot.utils import add_viadot_metadata_columns


class SapbwCredentials(BaseModel):
    """Checking for values in SAP BW credentials dictionary.

    Two key values are held in the Mindful connector:
        - ashost: Indicates the host name or IP address of a specific SAP
            application server.
        - client: Specifies the SAP logon parameter client.
        - passwd: Indicates the SAP logon parameter password.
        - sysnr: Indicates the SAP system number—the 2-byte code that identifies the
            system on the host.
        - user: Indicates the SAP logon parameter user.

    Args:
        BaseModel (pydantic.main.ModelMetaclass): A base class for creating
            Pydantic models.
    """

    ashost: str
    client: str
    passwd: str
    sysnr: str
    user: str


class Sapbw(Source):
    """Quering the SAP BW (SAP Business Warehouse) source using pyrfc library.

    Documentation to pyrfc can be found under:
        https://sap.github.io/PyRFC/pyrfc.html
    Documentation for SAP connection modules under:
        https://www.se80.co.uk/sap-function-modules/list/?index=rsr_mdx
    """

    def __init__(
        self,
        *args,
        credentials: SapbwCredentials | None = None,
        config_key: str = "sap_bw",
        **kwargs,
    ):
        """Create an instance of SAP BW.

        Args:
            credentials (Optional[SapbwCredentials], optional): SAP BW credentials.
                Defaults to None.
            config_key (str, optional): The key in the viadot config holding relevant
                credentials. Defaults to "sap_bw".

        Examples:
            sap_bw = Sapbw(
                credentials=credentials,
                config_key=config_key,
            )
            sap_bw.api_connection(
                ...
            )
            data_frame = sap_bw.to_df()

        Raises:
            CredentialError: If credentials are not provided in local_config or
                directly as a parameter.
        """
        credentials = credentials or get_source_credentials(config_key) or None
        if credentials is None:
            raise CredentialError("Missing credentials.")
        self.credentials = credentials

        validated_creds = dict(SapbwCredentials(**credentials))
        super().__init__(*args, credentials=validated_creds, **kwargs)

        self.query_output = None

    def _create_connection(self):
        """Create the connection with SAP BW.

        Returns:
            Connection: Connection to SAP.
        """

        return pyrfc.Connection(
            ashost=self.credentials.get("ashost"),
            sysnr=self.credentials.get("sysnr"),
            user=self.credentials.get("user"),
            passwd=self.credentials.get("passwd"),
            client=self.credentials.get("client"),
        )

    def api_connection(self, mdx_query: str) -> None:
        """Generate the SAP BW output dataset from MDX query.

        Args:
            mdx_query (str): The MDX query to be passed to connection.
        """
        conn = self._create_connection()

        query = textwrap.wrap(mdx_query, 75)
        properties = conn.call("RSR_MDX_CREATE_OBJECT", COMMAND_TEXT=query)

        datasetid = properties["DATASETID"]
        self.query_output = conn.call("RSR_MDX_GET_FLAT_DATA", DATASETID=datasetid)
        conn.close()

    @add_viadot_metadata_columns
    def to_df(self) -> pd.DataFrame:
        """Convert the SAP BW output JSON data into a dataframe.

        Args:


        Raises:
            ValidationError: Prints the original SAP error message in case of issues
                with MDX execution.

        Returns:
            pd.Dataframe: The response data as a pandas DataFrame plus viadot metadata.
        """
        raw_data = {}

        if self.query_output["RETURN"]["MESSAGE"] == "":
            results = self.query_output["DATA"]
            for cell in results:
                if cell["ROW"] not in raw_data:
                    raw_data[cell["ROW"]] = {}
                if "].[" not in cell["DATA"]:
                    raw_data[cell["ROW"]][cell["COLUMN"]] = cell["DATA"]
            rows = [raw_data[row] for row in raw_data]
            cols = [x["DATA"] for x in self.query_output["HEADER"]]

            df = pd.DataFrame(data=rows)
            df.columns = cols

        else:
            df = pd.DataFrame()
            raise ValidationError(self.query_output["RETURN"]["MESSAGE"])

        return df
