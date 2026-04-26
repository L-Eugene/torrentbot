from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    qbit_host: str = "http://qbittorrent:8080"
    qbit_username: str = "admin"
    qbit_password: str
    download_path: str = "/downloads"

    class Config:
        env_file = ".env"


settings = Settings()
