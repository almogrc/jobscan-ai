from firecrawl import Firecrawl
from pydantic import BaseModel, Field
import json

# מפתח ה-API החדש
app = Firecrawl(api_key="fc-5dcc7f58ded440b18e01b3321b074161")
hash_number = 1414141414

class Job(BaseModel):
    title: str = Field(description="The title of the job position")
    url: str = Field(description="The direct link to apply for this specific job")
    location: str = Field(description="The location of the job")
    id: str = Field(description="The job's serial number")
    job_hash: str = Field(description="The hashing with the hash ${hash_number} the mulitpication of the site's name, the URL of the job and the position")
    should_delete : bool = False
    created_at = Field(description="The date and time the job was uploded to the site")

class JobBoard(BaseModel):
    jobs: list[Job] = Field(description="List of all the jobs found on the page")

target_url = 'https://boards.greenhouse.io/openai'

try:
    print("[*] Sending the AI Agent to scan the jobs page...")
    
    # בגרסה 2 של הספרייה, קוראים ל-scrape ומעבירים לו את הסכמה ישירות לפורמט
    result = app.scrape(
        target_url,
        formats=[{
            "type": "json",
            "schema": JobBoard.model_json_schema()
        }]
    )

    # שולפים את המידע בצורה בטוחה
    if hasattr(result, 'json'):
        extracted_data = result.json
    elif isinstance(result, dict):
        extracted_data = result.get('json')
    else:
        extracted_data = result
        
    print("\n✅ BOOM! Your Jobs JSON:\n")
    print(json.dumps(extracted_data, indent=2, ensure_ascii=False))

except Exception as e:
    print(f"❌ Error: {e}")