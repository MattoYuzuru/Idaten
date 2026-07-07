package dev.idaten.companion.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ElevationGainedRecord
import androidx.health.connect.client.records.ExerciseRoute
import androidx.health.connect.client.records.ExerciseRouteResult
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.SpeedRecord
import androidx.health.connect.client.records.StepsCadenceRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import dev.idaten.companion.model.HealthAvailability
import dev.idaten.companion.model.HealthSample
import dev.idaten.companion.model.PermissionState
import dev.idaten.companion.model.RawHealthRun
import java.time.Duration
import java.time.Instant
import java.time.ZoneId

interface HealthConnectSource {
    val basePermissions: Set<String>
    val routePermission: String

    fun availability(): HealthAvailability

    suspend fun permissionState(): PermissionState

    suspend fun latestRuns(limit: Int = 20): List<RawHealthRun>

    fun withRoute(
        run: RawHealthRun,
        route: ExerciseRoute,
    ): RawHealthRun
}

class AndroidHealthConnectSource(
    private val context: Context,
) : HealthConnectSource {
    override val basePermissions: Set<String> =
        setOf(
            HealthPermission.getReadPermission(ExerciseSessionRecord::class),
            HealthPermission.getReadPermission(DistanceRecord::class),
            HealthPermission.getReadPermission(HeartRateRecord::class),
            HealthPermission.getReadPermission(SpeedRecord::class),
            HealthPermission.getReadPermission(StepsCadenceRecord::class),
            HealthPermission.getReadPermission(ElevationGainedRecord::class),
        )
    override val routePermission: String = "android.permission.health.READ_EXERCISE_ROUTES"

    private val client: HealthConnectClient
        get() = HealthConnectClient.getOrCreate(context)

    override fun availability(): HealthAvailability = HealthAvailabilityMapper.fromSdkStatus(HealthConnectClient.getSdkStatus(context))

    override suspend fun permissionState(): PermissionState {
        val availability = availability()
        if (availability != HealthAvailability.AVAILABLE) {
            return PermissionState(availability, emptySet(), basePermissions, routeGranted = false)
        }
        val granted = client.permissionController.getGrantedPermissions()
        return PermissionState(
            healthConnect = HealthAvailability.AVAILABLE,
            granted = granted,
            required = basePermissions,
            routeGranted = routePermission in granted,
        )
    }

    override suspend fun latestRuns(limit: Int): List<RawHealthRun> {
        val state = permissionState()
        if (!state.baseGranted) return emptyList()
        val sessions =
            client
                .readRecords(
                    ReadRecordsRequest(
                        recordType = ExerciseSessionRecord::class,
                        timeRangeFilter = TimeRangeFilter.before(Instant.now()),
                        ascendingOrder = false,
                        pageSize = limit.coerceIn(1, 100),
                    ),
                ).records
                .filter { it.exerciseType == ExerciseSessionRecord.EXERCISE_TYPE_RUNNING }
        return sessions.map { session -> readRun(session, state.canReadRoute) }
    }

    private suspend fun readRun(
        session: ExerciseSessionRecord,
        routePermissionGranted: Boolean,
    ): RawHealthRun {
        val range = TimeRangeFilter.between(session.startTime, session.endTime)
        val origins = setOf(session.metadata.dataOrigin)
        val distances =
            client
                .readRecords(
                    ReadRecordsRequest(DistanceRecord::class, range, origins),
                ).records
        val heartRates =
            client
                .readRecords(
                    ReadRecordsRequest(HeartRateRecord::class, range, origins),
                ).records
                .flatMap { record -> record.samples }
        val speeds =
            client
                .readRecords(
                    ReadRecordsRequest(SpeedRecord::class, range, origins),
                ).records
                .flatMap { record -> record.samples }
        val cadences =
            client
                .readRecords(
                    ReadRecordsRequest(StepsCadenceRecord::class, range, origins),
                ).records
                .flatMap { record -> record.samples }
        val elevations =
            client
                .readRecords(
                    ReadRecordsRequest(ElevationGainedRecord::class, range, origins),
                ).records
        val samples =
            buildList {
                heartRates.forEach { add(HealthSample(it.time.toString(), heartRate = it.beatsPerMinute.toInt())) }
                speeds.forEach { add(HealthSample(it.time.toString(), speedMetersPerSecond = it.speed.inMetersPerSecond)) }
                cadences.forEach { add(HealthSample(it.time.toString(), cadenceStepsPerMinute = it.rate)) }
                elevations.forEach {
                    add(HealthSample(it.endTime.toString(), elevationMeters = it.elevation.inMeters))
                }
            }.toMutableList()
        var routeConsentId: String? = null
        when (val route = session.exerciseRouteResult) {
            is ExerciseRouteResult.Data -> if (routePermissionGranted) samples += routeSamples(route.exerciseRoute)
            is ExerciseRouteResult.ConsentRequired -> routeConsentId = session.metadata.id
            is ExerciseRouteResult.NoData -> Unit
        }
        return RawHealthRun(
            externalId = session.metadata.id,
            startedAt = session.startTime.toString(),
            timezone = ZoneId.systemDefault().id,
            distanceMeters = distances.sumOf { it.distance.inMeters }.toLong().takeIf { it > 0 },
            elapsedSeconds = Duration.between(session.startTime, session.endTime).seconds,
            title = session.title,
            heartRates = heartRates.map { it.beatsPerMinute.toInt() },
            samples = samples.sortedBy(HealthSample::timestamp),
            routeConsentRecordId = routeConsentId,
        )
    }

    override fun withRoute(
        run: RawHealthRun,
        route: ExerciseRoute,
    ): RawHealthRun = run.copy(samples = (run.samples + routeSamples(route)).sortedBy(HealthSample::timestamp), routeConsentRecordId = null)

    private fun routeSamples(route: ExerciseRoute): List<HealthSample> =
        route.route.orEmpty().map {
            HealthSample(
                timestamp = it.time.toString(),
                latitude = it.latitude,
                longitude = it.longitude,
                elevationMeters = it.altitude?.inMeters,
            )
        }
}
