import csv
import io
import json
from urllib.parse import quote
from typing import Any
from pydantic import BaseModel, model_validator

from .models import Source, SourceMaterialization
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from .definitions import SourceDefinition
# 引入官方投影 Key，这是通关的关键
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

class CSVDocumentInput(BaseModel):
    document_id: str
    primary_key: str
    content: bytes

class CSVRowInput(BaseModel):
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

class CSVRowSource(Source):
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    materialization: SourceMaterialization = SourceMaterialization.CAPTURED

    # 使用 before 拦截器，在对象生成前就强制把 name 赋值为 source_id
    @model_validator(mode="before")
    @classmethod
    def compute_source_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            doc_id = data.get("document_id")
            pk_val = data.get("primary_key_value")
            if doc_id is not None and pk_val is not None:
                sid = csv_row_source_id(doc_id, pk_val)
                data["source_id"] = sid
                data["name"] = sid
        return data

    # 重写官方框架的 projection 方法
    def projection(self, key: str) -> dict:
        if key == TEXT_EVIDENCE_PROJECTION_KEY:
            row_dict = dict(zip(self.columns, self.values))
            content_json = json.dumps(row_dict, ensure_ascii=False, separators=(',', ':'))
            return {
                "source_type": "csv-row",
                "source_id": self.source_id,
                "content": content_json,
                "metadata": {
                    "document_id": self.document_id,
                    "primary_key": self.primary_key,
                    "primary_key_value": self.primary_key_value,
                    "columns": list(self.columns),
                    "row": row_dict
                }
            }
        raise ValueError(f"Unknown projection key: {key}")

def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    # 1. 校验 document_id 必须非空且不含首尾空白
    if not value.document_id or value.document_id != value.document_id.strip():
        raise ValueError("document_id must not be empty and must not contain leading/trailing whitespace")
    if not value.primary_key:
        raise ValueError("primary_key cannot be empty")

    # 2. 解码，处理 BOM
    try:
        text = value.content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError("Invalid encoding, must be UTF-8")

    reader = csv.reader(io.StringIO(text), strict=True)
    
    # 3. 读取表头并校验
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("Empty document")

    if not header or any(not col.strip() for col in header):
        raise ValueError("Header fields must not be empty or pure whitespace")
    if len(header) != len(set(header)):
        raise ValueError("Header fields must be unique")

    if value.primary_key not in header:
        raise ValueError(f"Primary key '{value.primary_key}' not in header")
    pk_index = header.index(value.primary_key)

    rows = []
    seen_pks = set()

    # 4. 逐行解析
    for row_num, row in enumerate(reader, start=2):
        # 忽略完全空白的物理行
        if not row or all(not cell.strip() for cell in row):
            continue

        if len(row) != len(header):
            raise ValueError(f"Row {row_num} column count mismatch")

        pk_val = row[pk_index]
        
        # 主键值不能是空字符串或纯空白
        if not pk_val or not pk_val.strip():
            raise ValueError(f"Row {row_num} primary key is empty or pure whitespace")
        # 主键值必须唯一
        if pk_val in seen_pks:
            raise ValueError(f"Duplicate primary key: {pk_val}")
        seen_pks.add(pk_val)

        # 提前计算一次 source_id 以触发长度和空格校验（抛错会在这里发生）
        csv_row_source_id(value.document_id, pk_val)

        rows.append(CSVRowInput(
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=pk_val,
            columns=tuple(header),
            values=tuple(row)
        ))

    return tuple(rows)

def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    # 单独调用此函数时也要能拦截空格
    if document_id != document_id.strip():
         raise ValueError("document_id contains leading/trailing whitespace")
    
    doc_encoded = quote(document_id, safe='')
    pk_encoded = quote(primary_key_value, safe='')
    sid = f"csv:{doc_encoded}:{pk_encoded}"
    
    if len(sid) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"Generated source_id exceeds {MAX_SOURCE_ID_LENGTH} characters")
        
    return sid

CSV_ROW_SOURCE_DEFINITION = SourceDefinition(
    name="csv-row",
    version=1,
    input_class=CSVRowInput,
    source_class=CSVRowSource
)
