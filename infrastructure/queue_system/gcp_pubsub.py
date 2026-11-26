import os
import json


def _use_emulator() -> bool:
    """
    Local runs talk to the Pub/Sub emulator on localhost:8085.
    On Cloud Run the platform sets K_SERVICE (services) or CLOUD_RUN_JOB (jobs);
    there the client must reach the real Pub/Sub, so we must NOT point it at
    localhost. PUBSUB_USE_EMULATOR=1/0 overrides the guess.
    """
    flag = os.getenv("PUBSUB_USE_EMULATOR")
    if flag is not None:
        return flag == "1"
    return not (os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_JOB"))


if _use_emulator():
    os.environ.setdefault("PUBSUB_EMULATOR_HOST", "localhost:8085")

from google.cloud import pubsub_v1                          # noqa: E402
from google.api_core.exceptions import AlreadyExists        # noqa: E402

DEFAULT_PROJECT_ID = (
    os.getenv("PUBSUB_PROJECT_ID")
    or os.getenv("GOOGLE_CLOUD_PROJECT")
    or "jobscan-local-dev"
)


class GCPPubSubClient:
    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or DEFAULT_PROJECT_ID
        self.publisher = pubsub_v1.PublisherClient()
        self.subscriber = pubsub_v1.SubscriberClient()

    def setup_topic_and_sub(self, topic_id: str, sub_id: str):
        """
        Local convenience: create the topic + subscription if missing.
        In the cloud, create them once with gcloud instead, including a
        dead-letter topic (--dead-letter-topic, --max-delivery-attempts) so a
        message that keeps failing stops being redelivered.
        """
        topic_path = self.publisher.topic_path(self.project_id, topic_id)
        sub_path = self.subscriber.subscription_path(self.project_id, sub_id)

        try:
            self.publisher.create_topic(request={"name": topic_path})
        except AlreadyExists:
            pass

        try:
            self.subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
        except AlreadyExists:
            pass

        return topic_path, sub_path

    def publish_message(self, topic_id: str, message_dict: dict):
        topic_path = self.publisher.topic_path(self.project_id, topic_id)
        data_bytes = json.dumps(message_dict).encode("utf-8")
        future = self.publisher.publish(topic_path, data_bytes)
        return future.result()

    def listen(self, sub_id: str, callback_func, max_messages: int = 4):
        """
        Start the streaming pull. The client runs callbacks on a pool of
        10 threads, so several messages are processed AT THE SAME TIME.
        max_messages caps how many are in flight at once.
        """
        sub_path = self.subscriber.subscription_path(self.project_id, sub_id)
        flow_control = pubsub_v1.types.FlowControl(max_messages=max_messages)
        future = self.subscriber.subscribe(sub_path, callback=callback_func, flow_control=flow_control)
        return future
