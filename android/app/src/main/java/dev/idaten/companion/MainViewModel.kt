package dev.idaten.companion

import androidx.health.connect.client.records.ExerciseRoute
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import dev.idaten.companion.data.ApiException
import dev.idaten.companion.data.DeviceRepository
import dev.idaten.companion.data.DeviceStatusResponse
import dev.idaten.companion.data.SyncRequest
import dev.idaten.companion.health.HealthConnectSource
import dev.idaten.companion.model.HealthConnectMapper
import dev.idaten.companion.model.PermissionState
import dev.idaten.companion.model.RunItem
import dev.idaten.companion.model.RunMappingResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class MainUiState(
    val linked: Boolean = false,
    val linking: Boolean = false,
    val linkCode: String = "",
    val status: DeviceStatusResponse? = null,
    val permissionState: PermissionState? = null,
    val runs: List<RunItem> = emptyList(),
    val loadingRuns: Boolean = false,
    val syncing: Boolean = false,
    val message: String? = null,
)

class MainViewModel(
    private val devices: DeviceRepository,
    private val health: HealthConnectSource,
    private val mapper: HealthConnectMapper = HealthConnectMapper(),
) : ViewModel() {
    private val mutableState = MutableStateFlow(MainUiState(linked = devices.isLinked()))
    val state: StateFlow<MainUiState> = mutableState.asStateFlow()

    init {
        refreshPermissions()
        if (devices.isLinked()) refreshStatus()
    }

    fun updateLinkCode(value: String) {
        mutableState.value = mutableState.value.copy(linkCode = value.take(16), message = null)
    }

    fun link() =
        viewModelScope.launch {
            val code = state.value.linkCode.trim()
            if (code.isEmpty()) {
                mutableState.value = state.value.copy(message = "Enter the code from Telegram")
                return@launch
            }
            mutableState.value = state.value.copy(linking = true, message = null)
            runCatching { devices.link(code) }
                .onSuccess {
                    mutableState.value =
                        state.value.copy(
                            linked = true,
                            linking = false,
                            linkCode = "",
                            message = "Device linked",
                        )
                    refreshStatus()
                }.onFailure { error ->
                    mutableState.value = state.value.copy(linking = false, message = safeMessage(error))
                }
        }

    fun refreshPermissions() =
        viewModelScope.launch {
            val result = runCatching { health.permissionState() }
            mutableState.value =
                state.value.copy(
                    permissionState = result.getOrNull(),
                    message = result.exceptionOrNull()?.let(::safeMessage),
                )
        }

    fun refreshStatus() =
        viewModelScope.launch {
            runCatching { devices.status() }
                .onSuccess { mutableState.value = state.value.copy(linked = true, status = it) }
                .onFailure { error ->
                    if (error is ApiException && error.code in setOf("INVALID_TOKEN", "TOKEN_REVOKED")) {
                        devices.unlinkLocal()
                        mutableState.value = state.value.copy(linked = false, status = null)
                    }
                    mutableState.value = state.value.copy(message = safeMessage(error))
                }
        }

    fun loadLatestRuns() =
        viewModelScope.launch {
            mutableState.value = state.value.copy(loadingRuns = true, message = null)
            runCatching { health.latestRuns() }
                .onSuccess { runs ->
                    mutableState.value =
                        state.value.copy(
                            loadingRuns = false,
                            runs = runs.map { RunItem(it, mapper.map(it)) },
                        )
                }.onFailure { error ->
                    mutableState.value = state.value.copy(loadingRuns = false, message = safeMessage(error))
                }
        }

    fun attachRoute(
        recordId: String,
        route: ExerciseRoute?,
    ) {
        if (route == null) {
            mutableState.value = state.value.copy(message = "Route access was not granted")
            return
        }
        mutableState.value =
            state.value.copy(
                runs =
                    state.value.runs.map { item ->
                        if (item.raw.routeConsentRecordId == recordId) {
                            val withRoute = health.withRoute(item.raw, route)
                            item.copy(raw = withRoute, mapping = mapper.map(withRoute))
                        } else {
                            item
                        }
                    },
                message = "Route added to this sync item",
            )
    }

    fun sync() =
        viewModelScope.launch {
            val ready = state.value.runs.mapNotNull { (it.mapping as? RunMappingResult.Ready)?.activity }
            if (!state.value.linked || ready.isEmpty()) {
                mutableState.value = state.value.copy(message = "No syncable runs")
                return@launch
            }
            mutableState.value = state.value.copy(syncing = true, message = null)
            runCatching { devices.sync(SyncRequest(state.value.status?.lastSyncCursor, ready)) }
                .onSuccess { response ->
                    val results = response.items.associateBy { it.externalId }
                    mutableState.value =
                        state.value.copy(
                            syncing = false,
                            runs =
                                state.value.runs.map { item ->
                                    val result = results[item.raw.externalId]
                                    item.copy(syncStatus = result?.status, syncMessage = result?.message)
                                },
                            message = "Sync completed",
                        )
                    refreshStatus()
                }.onFailure { error ->
                    mutableState.value = state.value.copy(syncing = false, message = safeMessage(error))
                }
        }

    private fun safeMessage(error: Throwable): String =
        when (error) {
            is ApiException -> error.message ?: error.code
            else -> "Operation failed"
        }

    class Factory(
        private val devices: DeviceRepository,
        private val health: HealthConnectSource,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = MainViewModel(devices, health) as T
    }
}
