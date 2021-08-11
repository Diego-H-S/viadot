import logging
import os
from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd
from prefect.engine import signals
from prefect.tasks.great_expectations import RunGreatExpectationsValidation
from prefect.utilities.tasks import defaults_from_attrs

import great_expectations as ge
from great_expectations.data_context import BaseDataContext
from great_expectations.data_context.types.base import (
    DataContextConfig,
    DatasourceConfig,
    FilesystemStoreBackendDefaults,
)
from great_expectations.validation_operators.types.validation_operator_result import (
    ValidationOperatorResult,
)


# Simplifies the setup and adds logging to the standard Prefect task
class RunGreatExpectationsValidation(RunGreatExpectationsValidation):
    """
    Task for running data validation with Great Expectations on a pandas DataFrame.
    See https://docs.prefect.io/api/latest/tasks/great_expectations.html#rungreatexpectationsvalidation
    for full documentation.

    Args:
        expectations_path (str): The path to the directory containing the expectation suites.
        df (pd.DataFrame): The DataFrame to validate.
    """

    def __init__(
        self,
        df: pd.DataFrame = None,
        expectations_path: str = None,
        evaluation_parameters: Dict[str, Any] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.df = df
        self.expectations_path = expectations_path
        self.evaluation_parameters = evaluation_parameters

    @staticmethod
    def _get_batch_kwargs(df: pd.DataFrame) -> dict:
        dataset = ge.from_pandas(df)
        return {"dataset": dataset, "datasource": "pandas"}

    @staticmethod
    def _get_ge_context_local(great_expectations_project_path: str) -> BaseDataContext:
        """
        This is configured to work with an in-memory pandas DataFrame.
        This setup allows us to run validations before (perhaps unnecessarily) writing any data
        to disk, as well as at any other stage.

        Currently using local storage.

        Args:
        great_expectations_project_path (str): The path to the Great Expectations project,
        eg. `/home/viadot/my_flow`. Expectation suites need to be placed inside the
        `expectations` folder, eg. `/home/viadot/my_flow/expectations/failure.json`.

        Returns:
            BaseDataContext: The GE context (ie. config) required to run the validations.
        """
        data_context_config = DataContextConfig(
            datasources={
                "pandas": DatasourceConfig(
                    class_name="PandasDatasource",
                    batch_kwargs_generators={},  # override the CSV default
                )
            },
            store_backend_defaults=FilesystemStoreBackendDefaults(
                great_expectations_project_path
            ),
            validation_operators={
                "action_list_operator": {
                    "class_name": "ActionListValidationOperator",
                    "action_list": [
                        {
                            "name": "store_validation_result",
                            "action": {"class_name": "StoreValidationResultAction"},
                        },
                        {
                            "name": "store_evaluation_params",
                            "action": {"class_name": "StoreEvaluationParametersAction"},
                        },
                        {
                            "name": "update_data_docs",
                            "action": {"class_name": "UpdateDataDocsAction"},
                        },
                    ],
                }
            },
        )
        context = BaseDataContext(project_config=data_context_config)
        return context

    @defaults_from_attrs("df", "expectations_path", "evaluation_parameters")
    def run(self, df: pd.DataFrame = None, expectations_path: str = None, **kwargs):

        great_expectations_project_path = str(Path(expectations_path).parent)

        batch_kwargs = self._get_batch_kwargs(df)
        context = self._get_ge_context_local(great_expectations_project_path)

        self.logger.info("Beginning validation run...")

        try:
            results = super().run(
                batch_kwargs=batch_kwargs,  # input data
                context=context,  # ~project config
                **kwargs,
            )
        except signals.FAIL as e:
            results = e.state.result

        # Show summary of results
        n_successful, n_expectations = self._get_stats_from_results(results)
        status = "success" if results.success else "failure"
        level = logging.INFO if results.success else logging.ERROR
        self.logger.log(
            msg=f"Validation finished with status '{status}'. {n_successful}/{n_expectations} test(s) passed.",
            level=level,
        )

        data_docs_path = os.path.join(
            great_expectations_project_path,
            "uncommitted",
            "data_docs",
            "local_site",
            "index.html",
        )
        self.logger.info(f"To explore the docs, open {data_docs_path} in a browser.")

        if not results.success:
            raise signals.FAIL(result=results)

        return results

    def _get_stats_from_results(
        self, result: ValidationOperatorResult
    ) -> Tuple[int, int]:
        result_identifier = result.list_validation_result_identifiers()[0]
        stats = result._list_validation_statistics()[result_identifier]
        n_successful = stats["successful_expectations"]
        n_expectations = stats["evaluated_expectations"]
        return n_successful, n_expectations
