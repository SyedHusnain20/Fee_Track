from sqlmodel import Field, SQLModel


class SystemSetting(SQLModel, table=True):
    """
    Key-value store for admin-configurable settings, e.g.:
    academic_year_reset_month, school_start_time, coaching_grace_minutes.
    Values are stored as strings and parsed by type at the application layer.
    """

    __tablename__ = "system_setting"

    key: str = Field(primary_key=True, max_length=100)
    value: str
