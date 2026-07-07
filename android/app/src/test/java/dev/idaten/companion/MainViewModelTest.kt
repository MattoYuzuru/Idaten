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
import dev.idaten.companion.model.HealthAvailability
import dev.idaten.companion.model.PermissionState
import dev.idaten.companion.model.RawHealthRun
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

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

    private class FakeHealth : HealthConnectSource {
        override val basePermissions = setOf("exercise", "distance")
        override val routePermission = "route"

        override fun availability() = HealthAvailability.AVAILABLE

        override suspend fun permissionState() =
            PermissionState(
                HealthAvailability.AVAILABLE,
                basePermissions,
                basePermissions,
                routeGranted = false,
            )

        override suspend fun latestRuns(limit: Int) =
            listOf(
                RawHealthRun(
                    externalId = "hc-1",
                    startedAt = "2026-07-06T06:00:00Z",
                    timezone = "Europe/Moscow",
                    distanceMeters = 5_000,
                    elapsedSeconds = 1_800,
                ),
            )

        override fun withRoute(
            run: RawHealthRun,
            route: ExerciseRoute,
        ) = run
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
