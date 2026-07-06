package dev.idaten.companion.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

data class HealthSample(
    val timestamp: String,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val elevationMeters: Double? = null,
    val heartRate: Int? = null,
    val speedMetersPerSecond: Double? = null,
    val cadenceStepsPerMinute: Double? = null,
)

data class RawHealthRun(
    val externalId: String,
    val startedAt: String,
    val timezone: String,
    val distanceMeters: Long?,
    val elapsedSeconds: Long,
    val title: String? = null,
    val heartRates: List<Int> = emptyList(),
    val samples: List<HealthSample> = emptyList(),
    val routeConsentRecordId: String? = null,
)

@Serializable
data class SyncSampleDto(
    val timestamp: String,
    val latitude: Double? = null,
    val longitude: Double? = null,
    @SerialName("elevation_m") val elevationMeters: Double? = null,
    @SerialName("heart_rate") val heartRate: Int? = null,
    @SerialName("speed_mps") val speedMetersPerSecond: Double? = null,
    @SerialName("cadence_spm") val cadenceStepsPerMinute: Double? = null,
)

@Serializable
data class SyncActivityDto(
    @SerialName("external_id") val externalId: String,
    @SerialName("started_at") val startedAt: String,
    val timezone: String,
    @SerialName("distance_m") val distanceMeters: Int,
    @SerialName("elapsed_time_sec") val elapsedSeconds: Int,
    val title: String? = null,
    @SerialName("avg_hr") val averageHeartRate: Int? = null,
    @SerialName("max_hr") val maximumHeartRate: Int? = null,
    val samples: List<SyncSampleDto> = emptyList(),
)

sealed interface RunMappingResult {
    data class Ready(
        val activity: SyncActivityDto,
    ) : RunMappingResult

    data class Invalid(
        val externalId: String,
        val reason: String,
    ) : RunMappingResult
}

class HealthConnectMapper {
    fun map(run: RawHealthRun): RunMappingResult {
        val distance = run.distanceMeters
        if (distance == null || distance <= 0 || distance > Int.MAX_VALUE) {
            return RunMappingResult.Invalid(run.externalId, "Distance is unavailable")
        }
        if (run.elapsedSeconds <= 0 || run.elapsedSeconds > Int.MAX_VALUE) {
            return RunMappingResult.Invalid(run.externalId, "Duration is invalid")
        }
        return RunMappingResult.Ready(
            SyncActivityDto(
                externalId = run.externalId,
                startedAt = run.startedAt,
                timezone = run.timezone,
                distanceMeters = distance.toInt(),
                elapsedSeconds = run.elapsedSeconds.toInt(),
                title = run.title,
                averageHeartRate =
                    run.heartRates
                        .takeIf(List<Int>::isNotEmpty)
                        ?.average()
                        ?.toInt(),
                maximumHeartRate = run.heartRates.maxOrNull(),
                samples =
                    run.samples.map { sample ->
                        SyncSampleDto(
                            timestamp = sample.timestamp,
                            latitude = sample.latitude,
                            longitude = sample.longitude,
                            elevationMeters = sample.elevationMeters,
                            heartRate = sample.heartRate,
                            speedMetersPerSecond = sample.speedMetersPerSecond,
                            cadenceStepsPerMinute = sample.cadenceStepsPerMinute,
                        )
                    },
            ),
        )
    }
}

enum class HealthAvailability { AVAILABLE, UPDATE_REQUIRED, UNAVAILABLE }

data class PermissionState(
    val healthConnect: HealthAvailability,
    val granted: Set<String>,
    val required: Set<String>,
    val routeGranted: Boolean,
) {
    val baseGranted: Boolean = healthConnect == HealthAvailability.AVAILABLE && granted.containsAll(required)
    val canReadRoute: Boolean = baseGranted && routeGranted
}

data class RunItem(
    val raw: RawHealthRun,
    val mapping: RunMappingResult,
    val syncStatus: String? = null,
    val syncMessage: String? = null,
)
