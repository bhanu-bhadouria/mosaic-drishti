"""
SQLAlchemy 2.0 ORM models for Mosaic Drishti.

All monetary values are exact decimals (Numeric) in INR; ratios are dimensionless
Numeric values. Timestamps are timezone-aware (timestamptz), stored as UTC;
display in IST in the presentation layer.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }


class Stock(Base):
    """Master record for every tracked equity instrument."""

    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True)  # e.g. "RELIANCE.NS"
    name: Mapped[str] = mapped_column(String(255))  # e.g. "Reliance Industries"
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    exchange: Mapped[str] = mapped_column(String(10))  # "NSE" or "BSE"
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    price_history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )
    financials: Mapped[list["FinancialData"]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )
    research_cache: Mapped[list["ResearchCache"]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Stock {self.symbol}>"


class PriceHistory(Base):
    """Daily OHLCV data for a stock. One row per (stock, date)."""

    __tablename__ = "price_history"
    __table_args__ = (UniqueConstraint("stock_id", "date", name="uq_price_stock_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    date: Mapped[date]
    open_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    stock: Mapped["Stock"] = relationship(back_populates="price_history")

    def __repr__(self) -> str:
        return f"<PriceHistory {self.stock_id} {self.date}>"


class FinancialData(Base):
    """Fundamental financials for annual or quarterly reporting periods."""

    __tablename__ = "financial_data"
    __table_args__ = (
        UniqueConstraint(
            "stock_id", "period_type", "period_date", name="uq_financial_stock_period"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    period_type: Mapped[str] = mapped_column(String(10))  # "annual" | "quarterly"
    period_date: Mapped[date]  # last day of the reporting period

    # Income statement
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    eps: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Balance-sheet / efficiency ratios
    debt_to_equity: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    roe: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # Return on Equity
    roce: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4)
    )  # Return on Capital Employed

    # Valuation multiples (point-in-time snapshot, not live)
    pe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    pb_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    stock: Mapped["Stock"] = relationship(back_populates="financials")

    def __repr__(self) -> str:
        return f"<FinancialData {self.stock_id} {self.period_type} {self.period_date}>"


class ResearchCache(Base):
    """Cached agent outputs to avoid re-running expensive LLM calls.

    Check expires_at before serving cached content; a past value means stale.
    """

    __tablename__ = "research_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(100))  # e.g. "fundamental_agent"
    research_type: Mapped[str] = mapped_column(String(100))  # e.g. "full_analysis"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]

    stock: Mapped["Stock"] = relationship(back_populates="research_cache")

    def __repr__(self) -> str:
        return f"<ResearchCache {self.agent_name} stock={self.stock_id}>"


__all__ = ["Base", "Stock", "PriceHistory", "FinancialData", "ResearchCache"]
