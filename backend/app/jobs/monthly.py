from datetime import UTC, datetime

from app.groups.monthly_service import MonthlyReportService


class MonthlyReportJob:
    def __init__(self, service: MonthlyReportService) -> None:
        self.service = service

    async def run(self, moment: datetime | None = None) -> int:
        return await self.service.generate_previous_month(moment or datetime.now(UTC))
