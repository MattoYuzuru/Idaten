package dev.idaten.companion

import dev.idaten.companion.model.HealthAvailability
import dev.idaten.companion.model.HealthConnectMapper
import dev.idaten.companion.model.HealthSample
import dev.idaten.companion.model.PermissionState
import dev.idaten.companion.model.RawHealthRun
import dev.idaten.companion.model.RunMappingResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HealthConnectMapperTest {
    private val mapper = HealthConnectMapper()

    @Test
    fun mapsHealthConnectRunAndSeries() {
        val mapped =
            mapper.map(
                run(
                    heartRates = listOf(140, 160),
                    samples =
                        listOf(
                            HealthSample(
                                timestamp = "2026-07-06T06:00:00Z",
                                latitude = 55.75,
                                longitude = 37.61,
                                heartRate = 140,
                                cadenceStepsPerMinute = 170.0,
                            ),
                        ),
                ),
            ) as RunMappingResult.Ready
        assertEquals(5_000, mapped.activity.distanceMeters)
        assertEquals(150, mapped.activity.averageHeartRate)
        assertEquals(160, mapped.activity.maximumHeartRate)
        assertEquals(
            55.75,
            mapped.activity.samples
                .single()
                .latitude,
        )
    }

    @Test
    fun optionalRecordsAreNotRequired() {
        val mapped = mapper.map(run()) as RunMappingResult.Ready
        assertNull(mapped.activity.averageHeartRate)
        assertTrue(mapped.activity.samples.isEmpty())
    }

    @Test
    fun missingRequiredDistanceIsItemError() {
        val mapped = mapper.map(run(distanceMeters = null))
        assertTrue(mapped is RunMappingResult.Invalid)
    }

    @Test
    fun permissionStateKeepsRouteSeparateFromBasePermissions() {
        val state =
            PermissionState(
                healthConnect = HealthAvailability.AVAILABLE,
                granted = setOf("exercise", "distance"),
                required = setOf("exercise", "distance"),
                routeGranted = false,
            )
        assertTrue(state.baseGranted)
        assertFalse(state.canReadRoute)
        assertTrue(state.copy(routeGranted = true).canReadRoute)
    }

    private fun run(
        distanceMeters: Long? = 5_000,
        heartRates: List<Int> = emptyList(),
        samples: List<HealthSample> = emptyList(),
    ) = RawHealthRun(
        externalId = "hc-1",
        startedAt = "2026-07-06T06:00:00Z",
        timezone = "Europe/Moscow",
        distanceMeters = distanceMeters,
        elapsedSeconds = 1_800,
        heartRates = heartRates,
        samples = samples,
    )
}
