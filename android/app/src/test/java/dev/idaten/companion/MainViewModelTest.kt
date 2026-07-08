package dev.idaten.companion

import androidx.health.connect.client.records.ExerciseRoute
import dev.idaten.companion.data.DeviceRepository
import dev.idaten.companion.data.DeviceStatusResponse
import dev.idaten.companion.data.IdatenApi
import dev.idaten.companion.data.InMemoryTokenStore
import dev.idaten.companion.data.LinkCompleteRequest
import dev.idaten.companion.data.LinkCompleteResponse
import dev.idaten.companion.data.SyncItemResponse
import dev.idaten.companion.data.SyncRequest
import dev.idaten.companion.data.SyncResponse
import dev.idaten.companion.health.HealthConnectSource
import dev.idaten.companion.health.HealthOnboardingState
import dev.idaten.companion.model.HealthAvailability
import dev.idaten.companion.model.HealthRunSearchResult
import dev.idaten.companion.model.PermissionState
import dev.idaten.companion.model.RawHealthRun
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.IOException

class MainViewModelTest {
    @get:Rule val mainDispatcherRule = MainDispatcherRule()

    @Test
    fun linkStatusLatestRunsAndItemSyncStateAreObservable() =
        runTest {
            val api = FakeApi()
            val devices = DeviceRepository(api, InMemoryTokenStore(), { "install" }, { "Pixel" }, { "9" })
            val viewModel = MainViewModel(devices, FakeHealth())

            assertFalse(viewModel.state.value.linked)
            viewModel.updateLinkCode("abcd1234")
            viewModel.link().join()
            assertTrue(viewModel.state.value.linked)
            assertEquals(
                "NEVER",
                viewModel.state.value.status
                    ?.lastSyncStatus,
            )

            viewModel.loadLatestRuns().join()
            assertEquals(1, viewModel.state.value.runs.size)
            viewModel.sync().join()
            assertEquals(
                "saved",
                viewModel.state.value.runs
                    .single()
                    .syncStatus,
            )
            assertEquals(
                "cursor-1",
                viewModel.state.value.status
                    ?.lastSyncCursor,
            )
        }

    @Test
    fun unavailableProviderBlocksPermissionRequestAndReads() =
        runTest {
            val health = FakeHealth(HealthAvailability.UNAVAILABLE)
            val viewModel =
                MainViewModel(
                    DeviceRepository(FakeApi(), InMemoryTokenStore(), { "install" }),
                    health,
                )

            assertEquals(HealthOnboardingState.UNSUPPORTED, viewModel.state.value.healthState)
            assertEquals(null, viewModel.requestBasePermissions())
            viewModel.loadLatestRuns().join()
            assertEquals(0, health.readCalls)
        }

    @Test
    fun foregroundRefreshesProviderAndPermissionState() =
        runTest {
            val health = FakeHealth(HealthAvailability.UPDATE_REQUIRED)
            val viewModel =
                MainViewModel(
                    DeviceRepository(FakeApi(), InMemoryTokenStore(), { "install" }),
                    health,
                )
            assertEquals(HealthOnboardingState.PROVIDER_UPDATE_REQUIRED, viewModel.state.value.healthState)

            health.currentAvailability = HealthAvailability.AVAILABLE
            health.granted = health.basePermissions
            viewModel.onForeground()

            assertEquals(HealthOnboardingState.READY, viewModel.state.value.healthState)
            assertTrue(health.permissionChecks >= 2)
        }

    @Test
    fun grantPartialDenyAndManualRetryRemainExplicit() =
        runTest {
            val health = FakeHealth(HealthAvailability.AVAILABLE).apply { granted = emptySet() }
            val viewModel =
                MainViewModel(
                    DeviceRepository(FakeApi(), InMemoryTokenStore(), { "install" }),
                    health,
                )

            assertEquals(health.basePermissions, viewModel.requestBasePermissions())
            assertFalse(health.basePermissions.contains(health.routePermission))
            assertEquals(null, viewModel.requestBasePermissions())
            health.granted = setOf("exercise")
            viewModel.onPermissionResult(setOf("exercise"))
            assertEquals(2, health.permissionChecks)
            assertEquals(HealthOnboardingState.PERMISSIONS_REQUIRED, viewModel.state.value.healthState)
            assertEquals(health.basePermissions, viewModel.requestBasePermissions())
            health.granted = emptySet()
            viewModel.onPermissionResult(emptySet())
            assertEquals(HealthOnboardingState.PERMISSIONS_REQUIRED, viewModel.state.value.healthState)
            assertEquals(health.basePermissions, viewModel.requestBasePermissions())
            health.granted = health.basePermissions
            viewModel.onPermissionResult(health.basePermissions)
            assertEquals(HealthOnboardingState.READY, viewModel.state.value.healthState)
        }

    @Test
    fun permissionResultIsRecheckedAgainstProviderState() =
        runTest {
            val health = FakeHealth(HealthAvailability.AVAILABLE).apply { granted = emptySet() }
            val viewModel =
                MainViewModel(
                    DeviceRepository(FakeApi(), InMemoryTokenStore(), { "install" }),
                    health,
                )

            assertEquals(health.basePermissions, viewModel.requestBasePermissions())
            health.granted = health.basePermissions
            viewModel.onPermissionResult(emptySet())

            assertEquals(HealthOnboardingState.READY, viewModel.state.value.healthState)
            assertEquals("Доступ к данным Health Connect предоставлен", viewModel.state.value.healthMessage)
        }

    @Test
    fun backendRefreshAlsoRefreshesHealthConnectAndShowsSuccess() =
        runTest {
            val health = FakeHealth(HealthAvailability.AVAILABLE).apply { granted = emptySet() }
            val store = InMemoryTokenStore().apply { write("token") }
            val viewModel =
                MainViewModel(
                    DeviceRepository(FakeApi(), store, { "install" }),
                    health,
                )
            assertEquals(HealthOnboardingState.PERMISSIONS_REQUIRED, viewModel.state.value.healthState)

            health.granted = health.basePermissions
            viewModel.refreshBackendAndHealth()

            assertEquals(HealthOnboardingState.READY, viewModel.state.value.healthState)
            assertEquals("Backend доступен", viewModel.state.value.backendMessage)
        }

    @Test
    fun repeatedProviderActionIsIgnoredUntilReturnThenRefreshed() =
        runTest {
            val health = FakeHealth(HealthAvailability.UPDATE_REQUIRED)
            val viewModel =
                MainViewModel(
                    DeviceRepository(FakeApi(), InMemoryTokenStore(), { "install" }),
                    health,
                )

            assertTrue(viewModel.startProviderAction())
            assertFalse(viewModel.startProviderAction())
            health.currentAvailability = HealthAvailability.AVAILABLE
            health.granted = health.basePermissions
            viewModel.providerActionFinished()
            assertEquals(HealthOnboardingState.READY, viewModel.state.value.healthState)
        }

    @Test
    fun backendFailureDoesNotMasqueradeAsHealthConnectFailure() =
        runTest {
            val store = InMemoryTokenStore().apply { write("token") }
            val viewModel =
                MainViewModel(
                    DeviceRepository(FailingStatusApi(), store, { "install" }),
                    FakeHealth(),
                )

            assertEquals(HealthOnboardingState.READY, viewModel.state.value.healthState)
            assertEquals(null, viewModel.state.value.healthMessage)
            assertEquals("Ошибка сети или backend", viewModel.state.value.backendMessage)
        }

    private class FakeHealth(
        var currentAvailability: HealthAvailability = HealthAvailability.AVAILABLE,
    ) : HealthConnectSource {
        override val basePermissions = setOf("exercise", "distance")
        override val routePermission = "route"
        var granted: Set<String> = if (currentAvailability == HealthAvailability.AVAILABLE) basePermissions else emptySet()
        var permissionChecks = 0
        var readCalls = 0

        override fun availability() = currentAvailability

        override suspend fun permissionState(): PermissionState {
            permissionChecks += 1
            return PermissionState(
                currentAvailability,
                granted,
                basePermissions,
                routeGranted = false,
            )
        }

        override suspend fun latestRuns(limit: Int): HealthRunSearchResult {
            readCalls += 1
            return HealthRunSearchResult(
                runs =
                    listOf(
                        RawHealthRun(
                            externalId = "hc-1",
                            startedAt = "2026-07-06T06:00:00Z",
                            timezone = "Europe/Moscow",
                            distanceMeters = 5_000,
                            elapsedSeconds = 1_800,
                        ),
                    ),
                searchedFrom = "2026-01-07T00:00:00Z",
                searchedUntil = "2026-07-06T00:00:00Z",
                pagesRead = 2,
                nonRunningCount = 3,
                exhausted = true,
                olderRecordsExist = false,
            )
        }

        override fun withRoute(
            run: RawHealthRun,
            route: ExerciseRoute,
        ) = run
    }

    private class FailingStatusApi : IdatenApi {
        override suspend fun completeLink(request: LinkCompleteRequest): LinkCompleteResponse = error("not used")

        override suspend fun status(token: String): DeviceStatusResponse = throw IOException("offline")

        override suspend fun sync(
            token: String,
            request: SyncRequest,
        ): SyncResponse = error("not used")
    }

    private class FakeApi : IdatenApi {
        private var cursor: String? = null

        override suspend fun completeLink(request: LinkCompleteRequest) = LinkCompleteResponse("device", "token", "health_connect:sync")

        override suspend fun status(token: String) =
            DeviceStatusResponse(
                deviceId = "device",
                name = "Pixel",
                scope = "health_connect:sync",
                lastSyncCursor = cursor,
                lastSyncStatus = if (cursor == null) "NEVER" else "SUCCESS",
            )

        override suspend fun sync(
            token: String,
            request: SyncRequest,
        ): SyncResponse {
            cursor = "cursor-1"
            return SyncResponse(
                cursor,
                listOf(SyncItemResponse("hc-1", "saved", activityId = "activity")),
            )
        }
    }
}
