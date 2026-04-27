import os
import json
from google.cloud import pubsub_v1
from google.api_core.exceptions import AlreadyExists

class GCPPubSubClient:
    def __init__(self, project_id: str = "jobscan-local-dev"):
        self.project_id = project_id
        self.publisher = pubsub_v1.PublisherClient()
        self.subscriber = pubsub_v1.SubscriberClient()

    def setup_topic_and_sub(self, topic_id: str, sub_id: str):
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

    def listen(self, sub_id: str, callback_func):
        """פונקציה חדשה שמרכזת את ההאזנה לתוך המחלקה"""
        sub_path = self.subscriber.subscription_path(self.project_id, sub_id)
        future = self.subscriber.subscribe(sub_path, callback=callback_func)
        return future