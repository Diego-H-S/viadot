"""Task to download data from SAP BW API into a Pandas DataFrame."""

from prefect import flow
from prefect.task_runners import ConcurrentTaskRunner

from viadot.orchestration.prefect.tasks import df_to_adls


@flow(
    name="SAP BW extraction to ADLS",
    description="Extract data from SAP BW and load it into Azure Data Lake Storage.",
    retries=1,
    retry_delay_seconds=60,
    task_runner=ConcurrentTaskRunner,
)
def sap_bw_to_adls() -> None:
    pass
