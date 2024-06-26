import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from O365 import Account
from O365.mailbox import MailBox
from pydantic import BaseModel

from viadot.config import get_source_credentials
from viadot.exceptions import CredentialError
from viadot.sources.base import Source
from viadot.utils import add_viadot_metadata_columns


class OUTLOOK_CREDENTIALS(BaseModel):
    client_id: str
    client_secret: str
    tenant_id: str


class Outlook(Source):
    """
    Class implementing the Outlook API.

    Documentation for this API is available at: https://o365.github.io/python-o365/latest/getting_started.html.
    """

    UTC = timezone.utc

    def __init__(
        self,
        credentials: Optional[Dict[str, Any]] = None,
        config_key: str = "outlook",
        *args: List[Any],
        **kwargs: Dict[str, Any],
    ):
        """
        Description:
            Outlook connector build for fetching Outlook API source.
            Data are fetched from start to end date range. If start or end date are not provided
            then flow fetched data from yestarday by default.

        Args:
            credentials (Optional[OUTLOOK_CREDENTIALS], optional): Outlook credentials.
                Defaults to None
            config_key (str, optional): The key in the viadot config holding relevant credentials.
                Defaults to "outlook".

        Raises:
            CredentialError: If credentials are not provided in local_config or directly as a parameter.
        """

        credentials = credentials or get_source_credentials(config_key) or None

        if credentials is None or not isinstance(credentials, dict):
            raise CredentialError("Missing credentials.")
        self.credentials = dict(OUTLOOK_CREDENTIALS(**credentials))

        logging.basicConfig()
        super().__init__(*args, credentials=self.credentials, **kwargs)
        self.logger.setLevel(logging.INFO)

    @staticmethod
    def _get_subfolders(
        folder_structure: dict,
        folder: MailBox,
        key_concat: str = "",
    ) -> Dict[str, List]:
        """
        Description:
            To retrieve all the subfolder in a MailBox folder.

        Args:
            folder_structure (dict): Dictionary where to save the data.
            folder (MailBox): The MailBox folder from where to extract the subfolders.
            key_concat (str, optional) Previous Mailbox folder structure to add to
                the actual subfolder. Defaults to "".

        Returns:
            Dict[str, List]: `folder_structure` dictionary is returned once it is updated.
        """
        if key_concat:
            tmp_key = key_concat.split("|")
            key_concat = key_concat.replace(f"|{tmp_key[-1]}", "")

        for subfolder in folder.get_folders():
            if subfolder:
                folder_structure.update(
                    {
                        "|".join([key_concat, folder.name, subfolder.name]).lstrip(
                            "|"
                        ): subfolder
                    }
                )

        if folder_structure:
            return folder_structure

    def _get_all_folders(
        self,
        mailbox: MailBox,
    ) -> dict:
        """
        Description:
            To retrieve all folders from a Mailbox object.

        Args:
            mailbox (MailBox): Outlook Mailbox object from where to extract all folder structure.

        Returns:
            dict: Every single folder and subfolder is returned as "parent (sub)folder|(sub)folder": Mailbox.
        """
        dict_folders = self._get_subfolders({}, mailbox)
        final_dict_folders = dict_folders.copy()

        # loop to get all subfolders
        while_dict_folders = {"key": "value"}
        while len(while_dict_folders) != 0:
            while_dict_folders = {}
            for key, value in list(dict_folders.items()):
                tmp_dict_folders = self._get_subfolders({}, value, key_concat=key)
                if tmp_dict_folders:
                    final_dict_folders.update(tmp_dict_folders)
                    while_dict_folders.update(tmp_dict_folders)

            dict_folders = while_dict_folders.copy()

        return final_dict_folders

    def _get_messages_from_mailbox(
        self,
        mailbox_name: str,
        dict_folder: dict,
        limit: int = 10000,
        address_limit: int = 8000,
        outbox_list: List[str] = ["Sent Items"],
    ) -> list:
        """
        Description:
            To retrieve all messages from all the mailboxes passed in the dictionary.

        Args:
            mailbox_name (str): Mailbox name.
            dict_folder (dict): Mailboxes dictionary holder, with the following structure:
                "parent (sub)folder|(sub)folder": Mailbox.
            limit (int, optional): Number of fetched top messages. Defaults to 10000.
            address_limit (int, optional): The maximum number of accepted characters in the sum
                of all email names. Defaults to 8000.
            outbox_list (List[str], optional): List of outbox folders to differenciate between
                Inboxes and Outboxes. Defaults to ["Sent Items"].

        Returns:
            list: A list with all messages from all Mailboxes.
        """
        data = []
        for key, value in list(dict_folder.items()):
            count = 0
            for message in value.get_messages(limit=limit):
                received_time = message.received
                date_obj = datetime.fromisoformat(str(received_time))
                if (
                    self.date_range_start_time.replace(tzinfo=self.UTC)
                    < date_obj
                    < self.date_range_end_time.replace(tzinfo=self.UTC)
                ):
                    count += 1
                    fetched = message.to_api_data()
                    sender_mail = fetched.get("from", None)
                    if sender_mail is not None:
                        sender_mail = fetched["from"]["emailAddress"]["address"]
                    recivers_list = fetched.get("toRecipients")
                    recivers = " "

                    if recivers_list is not None:
                        for reciver in recivers_list:
                            add_string = f", {reciver['emailAddress']['address']}"
                            if (
                                sum(list(map(len, [recivers, add_string])))
                                >= address_limit
                            ):
                                break
                            else:
                                recivers += add_string

                    categories = " "
                    if message.categories is not None:
                        categories = ", ".join(
                            categories for categories in message.categories
                        )

                    conversation_index = " "
                    if message.conversation_index is not None:
                        conversation_index = message.conversation_index

                    if isinstance(message.subject, str):
                        subject = message.subject.replace("\t", " ")
                    else:
                        subject = message.subject

                    row = {
                        "(sub)folder": value.name,
                        "conversation ID": fetched.get("conversationId"),
                        "conversation index": conversation_index,
                        "categories": categories,
                        "sender": sender_mail,
                        "subject": subject,
                        "recivers": recivers.strip(", "),
                        "received_time": fetched.get("receivedDateTime"),
                        "mail_adress": mailbox_name.split("@")[0]
                        .replace(".", "_")
                        .replace("-", "_"),
                    }
                    if any([x.lower() in key.lower() for x in outbox_list]):
                        row["Inbox"] = False
                    else:
                        row["Inbox"] = True

                    data.append(row)

            if count > 0:
                self.logger.info(f"folder: {key.ljust(76, '-')}  messages: {count}")

        return data

    def api_connection(
        self,
        mailbox_name: Optional[str] = None,
        request_retries: int = 10,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 10000,
        address_limit: int = 8000,
        outbox_list: List[str] = ["Sent Items"],
    ) -> pd.DataFrame:
        """
        Description:
            Download all the messages stored in a MailBox folder and subfolders.

        Args:
            mailbox_name (Optional[str], optional): Mailbox name. Defaults to None.
            request_retries (int, optional): How many times retries to authorizate. Defaults to 10.
            start_date (Optional[str], optional): A filtering start date parameter e.g. "2022-01-01".
                Defaults to None.
            end_date (Optional[str], optional): A filtering end date parameter e.g. "2022-01-02".
                Defaults to None.
            limit (int, optional): Number of fetched top messages. Defaults to 10000.
            address_limit (int, optional): The maximum number of accepted characters in the sum
                of all email names. Defaults to 8000.
            outbox_list (List[str], optional): List of outbox folders to differenciate between
                Inboxes and Outboxes. Defaults to ["Sent Items"].

        Returns:
            pd.DataFrame: All messages are stored in a pandas framwork.
        """
        self.mailbox_name = mailbox_name

        account = Account(
            (self.credentials["client_id"], self.credentials["client_secret"]),
            auth_flow_type="credentials",
            tenant_id=self.credentials["tenant_id"],
            main_resource=mailbox_name,
            request_retries=request_retries,
        )

        if account.authenticate():
            self.logger.info(f"{mailbox_name} Authenticated!")
        else:
            self.logger.info(f"{mailbox_name} NOT Authenticated!")

        mailbox_obj = account.mailbox()

        self.start_date = start_date
        self.end_date = end_date
        if self.start_date is not None and self.end_date is not None:
            self.date_range_end_time = datetime.strptime(self.end_date, "%Y-%m-%d")
            self.date_range_start_time = datetime.strptime(self.start_date, "%Y-%m-%d")
        else:
            self.date_range_start_time = date.today() - timedelta(days=1)
            self.date_range_end_time = date.today()

            min_time = datetime.min.time()
            self.date_range_end_time = datetime.combine(
                self.date_range_end_time, min_time
            )
            self.date_range_start_time = datetime.combine(
                self.date_range_start_time, min_time
            )
            self.outbox_list = outbox_list

        final_dict_folders = self._get_all_folders(mailbox_obj)

        self.data = self._get_messages_from_mailbox(
            mailbox_name=mailbox_name,
            dict_folder=final_dict_folders,
            limit=limit,
            address_limit=address_limit,
            outbox_list=outbox_list,
        )

    @add_viadot_metadata_columns
    def to_df(self) -> pd.DataFrame:
        """
        Description:
            Generate a Pandas Data Frame with the data in the Response object and metadata.

        Returns:
            pd.Dataframe: The response data as a Pandas Data Frame plus viadot metadata.
        """
        data_frame = pd.DataFrame(self.data)

        if data_frame.empty:
            self._handle_if_empty(
                if_empty="warn",
                message=f"No data was got from {self.mailbox_name}, days from {self.date_range_start_time} to {self.date_range_end_time}",
            )
        else:
            self.logger.info("Successfully downloaded data from the Mindful API.")

        return data_frame