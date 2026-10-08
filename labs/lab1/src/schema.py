from pydantic import BaseModel, Field
from typing import List, Optional

class Finding(BaseModel):
    cwe: Optional[str] = Field(None, description="CWE identifier if applicable")
    title: str
    severity: str  # low|medium|high
    rationale: str

class Analysis(BaseModel):
    llm_risks: List[str]  # e.g., ["LLM01", "LLM02"]
    findings: List[Finding]
