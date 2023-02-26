from pydantic import BaseModel
from typing import Optional, List

import difflib
import hashlib
import logging


class Message(BaseModel):
    from_id: Optional[int]
    channel_id: Optional[int]
    message_id: Optional[int]

    from_channel_id: Optional[int]
    from_message_id: Optional[int]

    forward_from_id: Optional[int]

    text: Optional[str]
    caption: Optional[str]

    media_ids: Optional[List[str]]

    # hash of message contents
    fingerprint: Optional[str]

    significant_text: Optional[bool] = False

    # channel_id without "-100" prefix
    chat_id: Optional[int]

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.chat_id = self.__chat_id()
        self.fingerprint = self.__gen_fingerprint()
        self.significant_text = len(self.text or self.caption or "") > 64

    def __chat_id(self) -> int:
        return int(str(self.channel_id).replace("-100", ""))

    def __gen_fingerprint(self) -> str:
        fingerprint_parts = [
            str(self.from_channel_id),
            str(self.from_message_id),
            self.text or self.caption or "",
            ",".join(self.media_ids),
        ]

        fingerprint = hashlib.sha256(";".join(fingerprint_parts).encode("utf-8")).hexdigest()

        return fingerprint[:16]

    def is_comparable(self) -> bool:
        ids_present = self.channel_id and self.message_id
        significant_content = self.media_ids or self.significant_text

        forward_self = self.forward_from_id and self.forward_from_id == self.from_id

        return ids_present and significant_content and not forward_self

    def __eq__(self, other: object) -> bool:  # noqa: CAC001, CCR001, CFQ004
        logging.info(f"Match messages: {self.fingerprint}/{other.fingerprint}")
        logging.debug(self.dict(exclude_unset=True))
        logging.debug(other.dict(exclude_unset=True))

        if not self.is_comparable():
            return NotImplemented

        if self.fingerprint == other.fingerprint:
            logging.info("Messages matched by fingerprint")
            return True

        same_message = self.channel_id and self.channel_id == other.channel_id and self.message_id == other.message_id

        if same_message:
            logging.info("Messages matched as same ones")
            return True

        same_forwarded = (
            self.from_channel_id
            and self.from_channel_id == other.from_channel_id
            and self.from_message_id == other.from_message_id
        )

        if same_forwarded:
            logging.info("Messages matched as same forwarded ones")
            return True

        compare_self = self.text or self.caption or ""
        compare_other = other.text or other.caption or ""

        if "" in (compare_self, compare_other):
            logging.debug(f"No data for {self.fingerprint} vs {other.fingerprint}: setting same_text_ratio to 0.0")
            same_text_ratio = 0.0
        else:
            same_text_ratio = difflib.SequenceMatcher(None, compare_self, compare_other).ratio()  # 0.00 to 1.00
            logging.debug(f"Same text ratio for {self.fingerprint} vs {other.fingerprint}: {same_text_ratio}")

        logging.debug(f"same_text_ratio is {same_text_ratio}")

        media_ratio_limit = 0.66

        text_ratio_limit = 0.75
        text_ratio_media_limit = 0.33
        if self.from_channel_id and self.from_message_id:
            text_ratio_limit = 0.66

        if self.significant_text and same_text_ratio > text_ratio_limit:
            logging.info(f"Messages matched by same text ratio: {round(same_text_ratio, 2)}")
            return True

        # same media

        if self.media_ids:
            same_media_list = list(set(self.media_ids) & set(other.media_ids))
            max_media_len = max(len(self.media_ids), len(other.media_ids))

            same_media_ratio = len(same_media_list) / max_media_len

            logging.debug(f"same_media_ratio is {same_media_ratio}")

            if self.significant_text and same_text_ratio > text_ratio_media_limit:
                logging.info(
                    "Messages matched by same text ratio with media presence: "
                    f"{round(same_media_ratio, 2)}, {round(same_text_ratio, 2)}",
                )
                return True

            if same_media_ratio >= media_ratio_limit:
                logging.info(
                    "Messages matched by same media ratio: "
                    f"{round(same_media_ratio, 2)}, {round(same_text_ratio, 2)}",
                )
                return True

        return False
