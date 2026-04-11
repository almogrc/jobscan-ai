from pydantic import BaseModel, Field

class Job(BaseModel):
    title: str = Field(description="The title of the job position")
    url: str = Field(description="The direct link to apply for this specific job")
    location: str = Field(description="The location of the job")
    id: str = Field(description="The job's serial number")
    created_at: str = Field(description="The date and time the job was uploaded to the site")
    should_delete: bool = False
    job_hash: str = "" 

class JobBoard(BaseModel):
    jobs: list[Job] = Field(description="List of all the jobs found on the page")