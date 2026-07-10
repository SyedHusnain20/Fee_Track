from sqlmodel import Field, SQLModel


class RollNumberCounter(SQLModel, table=True):
    """
    One row per cohort_code (e.g. "26" for a 2026 admission-year cohort).
    Step 9's roll-number generator increments last_sequence using
    SELECT ... FOR UPDATE to prevent two simultaneous admissions from
    colliding on the same sequence number.
    """

    __tablename__ = "roll_number_counter"

    cohort_code: str = Field(primary_key=True, max_length=2)
    last_sequence: int = Field(default=0)
