"""Task to download data from SAP BW API into a Pandas DataFrame."""

import pandas as pd
from prefect import get_run_logger, task

from viadot.orchestration.prefect.exceptions import MissingSourceCredentialsError
from viadot.orchestration.prefect.utils import get_credentials
from viadot.sources import Sapbw


@task(retries=3, log_prints=True, retry_delay_seconds=10, timeout_seconds=60 * 60)
def sap_bw_to_df() -> pd.DataFrame:
    pass
