package dev.idaten.companion

import dev.idaten.companion.health.selectLongestPlausibleSleep
import dev.idaten.companion.model.HealthConnectMapper
import dev.idaten.companion.model.RawHealthSleep
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Instant

class HealthConnectSleepTest {
    private val now = Instant.parse("2026-07-12T08:00:00Z")

    @Test
    fun freshLongestPlausibleSessionWinsDeterministically() {
        val selected =
            selectLongestPlausibleSleep(
                listOf(
                    sleep("short", "2026-07-12T07:00:00Z", 21_600),
                    sleep("long", "2026-07-12T06:00:00Z", 28_800),
                    sleep("stale", "2026-07-10T06:00:00Z", 32_400),
                    sleep("future", "2026-07-12T09:00:00Z", 36_000),
                    sleep("invalid", "2026-07-12T05:00:00Z", 90_000),
                ),
                now,
            )

        assertEquals("long", selected?.externalId)
    }

    @Test
    fun mapperSendsTypedSummaryWithoutSynthesizedQualityOrStages() {
        val mapped = HealthConnectMapper().mapSleep(sleep("sleep-1", "2026-07-12T06:00:00Z", 28_800))

        assertEquals(28_800, mapped?.durationSeconds)
        assertNull(mapped?.sleepQuality)
        assertNull(HealthConnectMapper().mapSleep(sleep("invalid", "2026-07-12T06:00:00Z", 90_000)))
    }

    private fun sleep(
        id: String,
        endedAt: String,
        duration: Long,
    ) = RawHealthSleep(
        externalId = id,
        startedAt = "2026-07-11T22:00:00Z",
        endedAt = endedAt,
        durationSeconds = duration,
        dataOrigin = "com.samsung.health",
        observedAt = now.toString(),
    )
}
