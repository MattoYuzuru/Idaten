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
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.SpeedRecord
import androidx.health.connect.client.records.StepsCadenceRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import dev.idaten.companion.model.HealthAvailability
import dev.idaten.companion.model.HealthRunSearchResult
import dev.idaten.companion.model.HealthSample
import dev.idaten.companion.model.PermissionState
import dev.idaten.companion.model.RawHealthRun
import dev.idaten.companion.model.RawHealthSleep
import dev.idaten.companion.model.RunSkipReason
import java.time.Duration
import java.time.Instant
import java.time.ZoneId

interface HealthConnectSource {
    val basePermissions: Set<String>
    val routePermission: String

    fun availability(): HealthAvailability

    suspend fun permissionState(): PermissionState

    suspend fun latestRuns(limit: Int = DEFAULT_RUN_LIMIT): HealthRunSearchResult

    suspend fun latestSleep(): RawHealthSleep? = null

    fun withRoute(
        run: RawHealthRun,
        route: ExerciseRoute,
    ): RawHealthRun
}

const val DEFAULT_RUN_LIMIT = 20
internal const val HEALTH_PAGE_SIZE = 20
internal const val MAX_HEALTH_PAGES = 10
internal const val HEALTH_LOOKBACK_DAYS = 180L
internal const val SLEEP_LOOKBACK_DAYS = 7L

internal data class SessionPage<T>(
    val records: List<T>,
    val nextToken: String?,
)

internal data class BoundedSelection<T>(
    val records: List<T>,
    val pagesRead: Int,
    val nonMatchingCount: Int,
    val exhausted: Boolean,
)

internal suspend fun <T> collectBoundedMatches(
    limit: Int,
    maximumPages: Int,
    loadPage: suspend (String?) -> SessionPage<T>,
    matches: (T) -> Boolean,
): BoundedSelection<T> {
    require(limit in 1..100)
    require(maximumPages > 0)
    val selected = mutableListOf<T>()
    var token: String? = null
    var pagesRead = 0
    var nonMatching = 0
    var exhausted = false
    while (selected.size < limit && pagesRead < maximumPages) {
        val page = loadPage(token)
        pagesRead += 1
        page.records.forEach { record ->
            if (matches(record) && selected.size < limit) {
                selected += record
            } else if (!matches(record)) {
                nonMatching += 1
            }
        }
        token = page.nextToken
        if (token == null) {
            exhausted = true
            break
        }
    }
    return BoundedSelection(selected, pagesRead, nonMatching, exhausted)
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
            HealthPermission.getReadPermission(ElevationGainedRecord::class),
        )
    override val routePermission: String = "android.permission.health.READ_EXERCISE_ROUTES"
    private val cadencePermission = HealthPermission.getReadPermission(StepsCadenceRecord::class)
    private val sleepPermission = HealthPermission.getReadPermission(SleepSessionRecord::class)

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
            sleepPermission = sleepPermission,
        )
    }

    override suspend fun latestSleep(): RawHealthSleep? {
        val state = permissionState()
        if (!state.sleepGranted) return null
        val now = Instant.now()
        val from = now.minus(Duration.ofDays(SLEEP_LOOKBACK_DAYS))
        val response =
            client.readRecords(
                ReadRecordsRequest(
                    recordType = SleepSessionRecord::class,
                    timeRangeFilter = TimeRangeFilter.between(from, now),
                    ascendingOrder = false,
                    pageSize = HEALTH_PAGE_SIZE,
                ),
            )
        val candidates =
            response.records.map { sleep ->
                RawHealthSleep(
                    externalId = sleep.metadata.id,
                    startedAt = sleep.startTime.toString(),
                    endedAt = sleep.endTime.toString(),
                    durationSeconds = Duration.between(sleep.startTime, sleep.endTime).seconds,
                    dataOrigin = sleep.metadata.dataOrigin.packageName,
                    observedAt = now.toString(),
                )
            }
        return selectLongestPlausibleSleep(candidates, now)
    }

    override suspend fun latestRuns(limit: Int): HealthRunSearchResult {
        require(limit in 1..100)
        val state = permissionState()
        val until = Instant.now()
        val from = until.minus(Duration.ofDays(HEALTH_LOOKBACK_DAYS))
        if (!state.baseGranted) {
            return HealthRunSearchResult(
                emptyList(),
                from.toString(),
                until.toString(),
                0,
                0,
                exhausted = true,
                olderRecordsExist = false,
            )
        }
        val selection =
            collectBoundedMatches(
                limit = limit,
                maximumPages = MAX_HEALTH_PAGES,
                loadPage = { pageToken ->
                    val response =
                        client.readRecords(
                            ReadRecordsRequest(
                                recordType = ExerciseSessionRecord::class,
                                timeRangeFilter = TimeRangeFilter.between(from, until),
                                ascendingOrder = false,
                                pageSize = HEALTH_PAGE_SIZE,
                                pageToken = pageToken,
                            ),
                        )
                    SessionPage(response.records, response.pageToken)
                },
                matches = { it.exerciseType == ExerciseSessionRecord.EXERCISE_TYPE_RUNNING },
            )
        val runs =
            selection.records.map { session ->
                runCatching { readRun(session, state.canReadRoute, cadencePermission in state.granted) }
                    .getOrElse {
                        RawHealthRun(
                            externalId = session.metadata.id,
                            startedAt = session.startTime.toString(),
                            timezone = ZoneId.systemDefault().id,
                            distanceMeters = null,
                            elapsedSeconds = Duration.between(session.startTime, session.endTime).seconds,
                            title = session.title,
                            readIssue = RunSkipReason.READ_ERROR,
                        )
                    }
            }
        val olderRecordsExist =
            if (runs.isEmpty()) {
                client
                    .readRecords(
                        ReadRecordsRequest(
                            recordType = ExerciseSessionRecord::class,
                            timeRangeFilter = TimeRangeFilter.before(from),
                            ascendingOrder = false,
                            pageSize = 1,
                        ),
                    ).records
                    .isNotEmpty()
            } else {
                false
            }
        return HealthRunSearchResult(
            runs = runs,
            searchedFrom = from.toString(),
            searchedUntil = until.toString(),
            pagesRead = selection.pagesRead,
            nonRunningCount = selection.nonMatchingCount,
            exhausted = selection.exhausted,
            olderRecordsExist = olderRecordsExist,
        )
    }

    private suspend fun readRun(
        session: ExerciseSessionRecord,
        routePermissionGranted: Boolean,
        cadencePermissionGranted: Boolean,
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
            if (cadencePermissionGranted) {
                client
                    .readRecords(
                        ReadRecordsRequest(StepsCadenceRecord::class, range, origins),
                    ).records
                    .flatMap { record -> record.samples }
            } else {
                emptyList()
            }
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

internal fun selectLongestPlausibleSleep(
    records: List<RawHealthSleep>,
    now: Instant,
): RawHealthSleep? =
    records
        .filter { record ->
            val endedAt = runCatching { record.endedAt?.let(Instant::parse) }.getOrNull()
            val duration = record.durationSeconds
            endedAt != null &&
                duration != null &&
                duration in 1..86_400 &&
                !endedAt.isAfter(now) &&
                !endedAt.isBefore(now.minus(Duration.ofHours(36)))
        }.maxWithOrNull(
            compareBy<RawHealthSleep> { it.durationSeconds ?: 0 }
                .thenBy { it.endedAt.orEmpty() }
                .thenBy { it.externalId },
        )
