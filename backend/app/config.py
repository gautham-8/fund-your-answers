from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "viva"

    jwt_secret: str = "change-me"
    jwt_expire_hours: int = 72

    gemini_api_key: str = ""
    gemini_analysis_model: str = "gemini-3.5-flash-lite"
    gemini_viva_model: str = "gemini-3.5-flash-lite"
    gemini_scoring_model: str = "gemini-3.5-flash-lite"
    # Tried in order when the main model is overloaded (503/429) or times out.
    gemini_fallback_models: str = ""
    # Per-model wait before moving to the next model.
    gemini_timeout_seconds: int = 60

    cors_origins: str = "http://localhost:5173"
    # Folder with the built frontend (set in the Docker image); empty = don't serve it.
    static_dir: str = ""

    max_pdf_mb: int = 20
    max_audio_mb: int = 15
    num_questions: int = 4
    # Below this confidence (0-1) a rubric score is flagged "needs review".
    review_confidence_threshold: float = 0.6
    # Share of the final grade that comes from the viva (the rest is the grader's mark); instructors change it per assignment.
    default_viva_weight: float = 0.3


settings = Settings()

DEFAULT_RUBRIC = [
    {"name": "Accuracy", "description": "Are the student's explanations technically correct?"},
    {"name": "Reasoning depth", "description": "Does the student explain why they made their choices, not just what they did?"},
    {"name": "Specificity", "description": "Does the student refer to concrete details of their own work?"},
    {"name": "Clarity", "description": "Is the explanation coherent and easy to follow? (Judge content, not accent or fluency.)"},
]
