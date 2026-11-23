import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from knowcel.common.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Access(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACCESS_UNSPECIFIED: _ClassVar[Access]
    ACCESS_PUBLIC: _ClassVar[Access]
    ACCESS_TEAM: _ClassVar[Access]

class JobStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    JOB_STATUS_UNSPECIFIED: _ClassVar[JobStatus]
    JOB_STATUS_PENDING_UPLOAD: _ClassVar[JobStatus]
    JOB_STATUS_QUEUED: _ClassVar[JobStatus]
    JOB_STATUS_PROCESSING: _ClassVar[JobStatus]
    JOB_STATUS_DONE: _ClassVar[JobStatus]
    JOB_STATUS_FAILED: _ClassVar[JobStatus]

class JobStage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    JOB_STAGE_UNSPECIFIED: _ClassVar[JobStage]
    JOB_STAGE_EXTRACTING: _ClassVar[JobStage]
    JOB_STAGE_CHUNKING: _ClassVar[JobStage]
    JOB_STAGE_EMBEDDING: _ClassVar[JobStage]
    JOB_STAGE_STORING: _ClassVar[JobStage]

class ConnectorHealth(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONNECTOR_HEALTH_UNSPECIFIED: _ClassVar[ConnectorHealth]
    CONNECTOR_HEALTH_HEALTHY: _ClassVar[ConnectorHealth]
    CONNECTOR_HEALTH_DEGRADED: _ClassVar[ConnectorHealth]
    CONNECTOR_HEALTH_FAILING: _ClassVar[ConnectorHealth]
    CONNECTOR_HEALTH_STALE: _ClassVar[ConnectorHealth]
    CONNECTOR_HEALTH_UNKNOWN: _ClassVar[ConnectorHealth]
ACCESS_UNSPECIFIED: Access
ACCESS_PUBLIC: Access
ACCESS_TEAM: Access
JOB_STATUS_UNSPECIFIED: JobStatus
JOB_STATUS_PENDING_UPLOAD: JobStatus
JOB_STATUS_QUEUED: JobStatus
JOB_STATUS_PROCESSING: JobStatus
JOB_STATUS_DONE: JobStatus
JOB_STATUS_FAILED: JobStatus
JOB_STAGE_UNSPECIFIED: JobStage
JOB_STAGE_EXTRACTING: JobStage
JOB_STAGE_CHUNKING: JobStage
JOB_STAGE_EMBEDDING: JobStage
JOB_STAGE_STORING: JobStage
CONNECTOR_HEALTH_UNSPECIFIED: ConnectorHealth
CONNECTOR_HEALTH_HEALTHY: ConnectorHealth
CONNECTOR_HEALTH_DEGRADED: ConnectorHealth
CONNECTOR_HEALTH_FAILING: ConnectorHealth
CONNECTOR_HEALTH_STALE: ConnectorHealth
CONNECTOR_HEALTH_UNKNOWN: ConnectorHealth

class Job(_message.Message):
    __slots__ = ("id", "document_id", "filename", "content_type", "status", "error", "chunk_count", "create_time", "update_time", "progress", "stage", "owner_id")
    ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    CHUNK_COUNT_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    UPDATE_TIME_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    OWNER_ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    document_id: str
    filename: str
    content_type: str
    status: JobStatus
    error: str
    chunk_count: int
    create_time: _timestamp_pb2.Timestamp
    update_time: _timestamp_pb2.Timestamp
    progress: int
    stage: JobStage
    owner_id: str
    def __init__(self, id: _Optional[str] = ..., document_id: _Optional[str] = ..., filename: _Optional[str] = ..., content_type: _Optional[str] = ..., status: _Optional[_Union[JobStatus, str]] = ..., error: _Optional[str] = ..., chunk_count: _Optional[int] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., update_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., progress: _Optional[int] = ..., stage: _Optional[_Union[JobStage, str]] = ..., owner_id: _Optional[str] = ...) -> None: ...

class CreateUploadRequest(_message.Message):
    __slots__ = ("filename", "content_type", "size_bytes", "title", "sha256", "access", "team_ids")
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    ACCESS_FIELD_NUMBER: _ClassVar[int]
    TEAM_IDS_FIELD_NUMBER: _ClassVar[int]
    filename: str
    content_type: str
    size_bytes: int
    title: str
    sha256: str
    access: Access
    team_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, filename: _Optional[str] = ..., content_type: _Optional[str] = ..., size_bytes: _Optional[int] = ..., title: _Optional[str] = ..., sha256: _Optional[str] = ..., access: _Optional[_Union[Access, str]] = ..., team_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class CreateUploadResponse(_message.Message):
    __slots__ = ("job", "upload_url")
    JOB_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_URL_FIELD_NUMBER: _ClassVar[int]
    job: Job
    upload_url: str
    def __init__(self, job: _Optional[_Union[Job, _Mapping]] = ..., upload_url: _Optional[str] = ...) -> None: ...

class ReplaceUploadRequest(_message.Message):
    __slots__ = ("document_id", "filename", "content_type", "size_bytes", "sha256")
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    document_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    def __init__(self, document_id: _Optional[str] = ..., filename: _Optional[str] = ..., content_type: _Optional[str] = ..., size_bytes: _Optional[int] = ..., sha256: _Optional[str] = ...) -> None: ...

class ReplaceUploadResponse(_message.Message):
    __slots__ = ("job", "upload_url")
    JOB_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_URL_FIELD_NUMBER: _ClassVar[int]
    job: Job
    upload_url: str
    def __init__(self, job: _Optional[_Union[Job, _Mapping]] = ..., upload_url: _Optional[str] = ...) -> None: ...

class CompleteUploadRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class CompleteUploadResponse(_message.Message):
    __slots__ = ("job",)
    JOB_FIELD_NUMBER: _ClassVar[int]
    job: Job
    def __init__(self, job: _Optional[_Union[Job, _Mapping]] = ...) -> None: ...

class GetJobRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class GetJobResponse(_message.Message):
    __slots__ = ("job",)
    JOB_FIELD_NUMBER: _ClassVar[int]
    job: Job
    def __init__(self, job: _Optional[_Union[Job, _Mapping]] = ...) -> None: ...

class ListJobsRequest(_message.Message):
    __slots__ = ("page",)
    PAGE_FIELD_NUMBER: _ClassVar[int]
    page: _common_pb2.PageRequest
    def __init__(self, page: _Optional[_Union[_common_pb2.PageRequest, _Mapping]] = ...) -> None: ...

class ListJobsResponse(_message.Message):
    __slots__ = ("jobs", "page")
    JOBS_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    jobs: _containers.RepeatedCompositeFieldContainer[Job]
    page: _common_pb2.PageResponse
    def __init__(self, jobs: _Optional[_Iterable[_Union[Job, _Mapping]]] = ..., page: _Optional[_Union[_common_pb2.PageResponse, _Mapping]] = ...) -> None: ...

class WatchJobRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class WatchJobResponse(_message.Message):
    __slots__ = ("job",)
    JOB_FIELD_NUMBER: _ClassVar[int]
    job: Job
    def __init__(self, job: _Optional[_Union[Job, _Mapping]] = ...) -> None: ...

class ReprocessJobRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class ReprocessJobResponse(_message.Message):
    __slots__ = ("job",)
    JOB_FIELD_NUMBER: _ClassVar[int]
    job: Job
    def __init__(self, job: _Optional[_Union[Job, _Mapping]] = ...) -> None: ...

class Connector(_message.Message):
    __slots__ = ("id", "name", "kind", "enabled", "health", "interval_seconds", "last_sync_start_time", "last_sync_end_time", "last_success_time", "documents_synced", "last_error")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    HEALTH_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    LAST_SYNC_START_TIME_FIELD_NUMBER: _ClassVar[int]
    LAST_SYNC_END_TIME_FIELD_NUMBER: _ClassVar[int]
    LAST_SUCCESS_TIME_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_SYNCED_FIELD_NUMBER: _ClassVar[int]
    LAST_ERROR_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    kind: str
    enabled: bool
    health: ConnectorHealth
    interval_seconds: int
    last_sync_start_time: _timestamp_pb2.Timestamp
    last_sync_end_time: _timestamp_pb2.Timestamp
    last_success_time: _timestamp_pb2.Timestamp
    documents_synced: int
    last_error: str
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., kind: _Optional[str] = ..., enabled: _Optional[bool] = ..., health: _Optional[_Union[ConnectorHealth, str]] = ..., interval_seconds: _Optional[int] = ..., last_sync_start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., last_sync_end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., last_success_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., documents_synced: _Optional[int] = ..., last_error: _Optional[str] = ...) -> None: ...

class ListConnectorsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListConnectorsResponse(_message.Message):
    __slots__ = ("connectors",)
    CONNECTORS_FIELD_NUMBER: _ClassVar[int]
    connectors: _containers.RepeatedCompositeFieldContainer[Connector]
    def __init__(self, connectors: _Optional[_Iterable[_Union[Connector, _Mapping]]] = ...) -> None: ...

class GetConnectorRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class GetConnectorResponse(_message.Message):
    __slots__ = ("connector",)
    CONNECTOR_FIELD_NUMBER: _ClassVar[int]
    connector: Connector
    def __init__(self, connector: _Optional[_Union[Connector, _Mapping]] = ...) -> None: ...

class SearchConnectorsRequest(_message.Message):
    __slots__ = ("query", "connector_ids", "limit", "team_ids")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    CONNECTOR_IDS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    TEAM_IDS_FIELD_NUMBER: _ClassVar[int]
    query: str
    connector_ids: _containers.RepeatedScalarFieldContainer[str]
    limit: int
    team_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, query: _Optional[str] = ..., connector_ids: _Optional[_Iterable[str]] = ..., limit: _Optional[int] = ..., team_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class SearchConnectorsResponse(_message.Message):
    __slots__ = ("snippets", "unavailable_connectors")
    SNIPPETS_FIELD_NUMBER: _ClassVar[int]
    UNAVAILABLE_CONNECTORS_FIELD_NUMBER: _ClassVar[int]
    snippets: _containers.RepeatedCompositeFieldContainer[ConnectorSnippet]
    unavailable_connectors: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, snippets: _Optional[_Iterable[_Union[ConnectorSnippet, _Mapping]]] = ..., unavailable_connectors: _Optional[_Iterable[str]] = ...) -> None: ...

class ConnectorSnippet(_message.Message):
    __slots__ = ("connector", "title", "text", "source_url", "external_id")
    CONNECTOR_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    SOURCE_URL_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_ID_FIELD_NUMBER: _ClassVar[int]
    connector: str
    title: str
    text: str
    source_url: str
    external_id: str
    def __init__(self, connector: _Optional[str] = ..., title: _Optional[str] = ..., text: _Optional[str] = ..., source_url: _Optional[str] = ..., external_id: _Optional[str] = ...) -> None: ...
