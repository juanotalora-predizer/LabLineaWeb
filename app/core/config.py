from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Configuración leída de variables de entorno o del archivo .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # En producción no se expone el esquema OpenAPI (reduce la superficie visible).
    entorno: Literal["desarrollo", "pruebas", "produccion"] = "desarrollo"

    # Dominio bajo el que viven los laboratorios (<lab>.<dominio>) y el Admin Hub (admin.<dominio>).
    # Cualquier otra cabecera Host se rechaza (spec infraestructura/0005). Producción: lablinea.cionetworks.com
    dominio_base: str = "lablinea.localhost"

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "lablinea_dev"
    db_name_test: str = "lablinea_test"

    # Dueño de los esquemas: solo migraciones (spec infraestructura/0007).
    db_owner_user: str = "lablinea_owner"
    db_owner_password: SecretStr

    # Rol de la aplicación: sin privilegios de dueño, para que RLS se aplique.
    db_app_user: str = "lablinea_app"
    db_app_password: SecretStr

    # Rol del Admin Hub: solo el esquema plataforma, sin acceso a lab.
    db_plataforma_user: str = "lablinea_plataforma"
    db_plataforma_password: SecretStr

    @property
    def base_aplicacion(self) -> str:
        """Base que usa la aplicación: la de prueba cuando corre la suite de pruebas."""
        return self.db_name_test if self.entorno == "pruebas" else self.db_name

    def _url(self, usuario: str, clave: SecretStr, base: str) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=usuario,
            password=clave.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=base,
        )

    def url_app(self, base: str | None = None) -> URL:
        return self._url(self.db_app_user, self.db_app_password, base or self.base_aplicacion)

    def url_owner(self, base: str | None = None) -> URL:
        return self._url(self.db_owner_user, self.db_owner_password, base or self.db_name)

    def url_plataforma(self, base: str | None = None) -> URL:
        return self._url(self.db_plataforma_user, self.db_plataforma_password, base or self.base_aplicacion)


@lru_cache
def get_settings() -> Settings:
    return Settings()
