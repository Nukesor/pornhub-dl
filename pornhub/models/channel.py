"""The db model for a channel."""
from sqlalchemy import Column, func
from sqlalchemy.types import (
    DateTime,
    String,
)

from pornhub.db import base


class Channel(base):
    """The model for a channel."""

    __tablename__ = "channel"

    id = Column(String, primary_key=True)
    name = Column(String)

    last_scan = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    def __init__(self, channel_id, name):
        """Create a new channel."""
        self.id = channel_id
        self.name = name

    @staticmethod
    def get_or_create(session, channel_id, name):
        """Get an existing channel or create a new one."""
        channel = session.query(Channel).get(channel_id)

        if channel is None:
            channel = Channel(channel_id, name)
            session.add(channel)
            session.commit()

        return channel
