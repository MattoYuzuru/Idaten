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
import dev.idaten.companion.health.HealthOnboardingState
import dev.idaten.companion.model.HealthConnectMapper
import dev.idaten.companion.model.PermissionState
import dev.idaten.companion.model.RunItem
import dev.idaten.companion.model.RunMappingResult
import dev.idaten.companion.model.RunSearchSummary
import dev.idaten.companion.model.RunSkipReason
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class MainUiState(
    val linked: Boolean = false,
    val linking: Boolean = false,
    val linkCode: String = "",
    val status: DeviceStatusResponse? = null,
    val healthState: HealthOnboardingState = HealthOnboardingState.CHECKING,
    val permissionState: PermissionState? = null,
    val runs: List<RunItem> = emptyList(),
    val runSearchSummary: RunSearchSummary? = null,
    val loadingRuns: Boolean = false,
    val syncing: Boolean = false,
    val permissionRequestInFlight: Boolean = false,
    val providerActionInFlight: Boolean = false,
    val healthMessage: String? = null,
    val backendMessage: String? = null,
)

class MainViewModel(
    private val devices: DeviceRepository,
    private val health: HealthConnectSource,
    private val mapper: HealthConnectMapper = HealthConnectMapper(),
) : ViewModel() {
    private val mutableState = MutableStateFlow(MainUiState(linked = devices.isLinked()))
    val state: StateFlow<MainUiState> = mutableState.asStateFlow()
    private var healthRefreshGeneration = 0

    init {
        refreshHealth()
        if (devices.isLinked()) refreshStatus()
    }

    fun updateLinkCode(value: String) {
        mutableState.value = mutableState.value.copy(linkCode = value.take(16), backendMessage = null)
    }

    fun link() =
        viewModelScope.launch {
            val code = state.value.linkCode.trim()
            if (code.isEmpty()) {
                mutableState.value = state.value.copy(backendMessage = "Введите код из Telegram")
                return@launch
            }
            mutableState.value = state.value.copy(linking = true, backendMessage = null)
            runCatching { devices.link(code) }
                .onSuccess {
                    mutableState.value =
                        state.value.copy(
                            linked = true,
                            linking = false,
                            linkCode = "",
                            backendMessage = "Устройство привязано",
                        )
                    refreshStatus()
                }.onFailure { error ->
                    mutableState.value = state.value.copy(linking = false, backendMessage = safeMessage(error))
                }
        }

    fun refreshHealth() =
        refreshHealthState(
            failureMessage = "Не удалось проверить Health Connect",
        )

    private fun refreshHealthState(
        checkingMessage: String? = null,
        successMessage: (PermissionState) -> String? = { null },
        failureMessage: String,
    ) = viewModelScope.launch {
        val generation = ++healthRefreshGeneration
        mutableState.value = state.value.copy(healthState = HealthOnboardingState.CHECKING, healthMessage = checkingMessage)
        val result = runCatching { health.permissionState() }
        if (generation != healthRefreshGeneration) return@launch
        val permissionState = result.getOrNull()
        mutableState.value =
            state.value.copy(
                permissionState = permissionState,
                healthState = permissionState?.onboardingState ?: HealthOnboardingState.UNSUPPORTED,
                healthMessage = permissionState?.let(successMessage) ?: result.exceptionOrNull()?.let { failureMessage },
            )
    }

    fun requestBasePermissions(): Set<String>? {
        val current = state.value
        if (
            current.healthState != HealthOnboardingState.PERMISSIONS_REQUIRED ||
            current.permissionRequestInFlight
        ) {
            return null
        }
        val permissions = current.permissionState?.required ?: return null
        mutableState.value = current.copy(permissionRequestInFlight = true, healthMessage = null)
        return permissions
    }

    fun onPermissionResult(granted: Set<String>) {
        val previous =
            state.value.permissionState
                ?: run {
                    mutableState.value = state.value.copy(permissionRequestInFlight = false)
                    refreshHealth()
                    return
                }
        val permissionState = previous.copy(granted = granted)
        mutableState.value =
            state.value.copy(
                permissionRequestInFlight = false,
                permissionState = permissionState,
                healthState = permissionState.onboardingState,
                healthMessage = "Перепроверяем фактические разрешения Health Connect…",
            )
        refreshHealthState(
            checkingMessage = "Перепроверяем фактические разрешения Health Connect…",
            successMessage = ::permissionResultMessage,
            failureMessage = "Не удалось перепроверить разрешения Health Connect",
        )
    }

    fun startProviderAction(): Boolean {
        val current = state.value
        if (
            current.healthState != HealthOnboardingState.PROVIDER_UPDATE_REQUIRED ||
            current.providerActionInFlight
        ) {
            return false
        }
        mutableState.value = current.copy(providerActionInFlight = true, healthMessage = null)
        return true
    }

    fun providerActionFinished(started: Boolean = true) {
        mutableState.value =
            state.value.copy(
                providerActionInFlight = false,
                healthMessage = if (started) null else "Не удалось открыть установку или настройки Health Connect",
            )
        refreshHealth()
    }

    fun onForeground() {
        refreshHealth()
    }

    fun refreshStatus() = refreshBackendStatus(showSuccess = false)

    fun refreshBackendAndHealth() {
        refreshHealth()
        refreshBackendStatus(showSuccess = true)
    }

    private fun refreshBackendStatus(showSuccess: Boolean) =
        viewModelScope.launch {
            runCatching { devices.status() }
                .onSuccess {
                    mutableState.value =
                        state.value.copy(
                            linked = true,
                            status = it,
                            backendMessage = if (showSuccess) "Backend доступен" else state.value.backendMessage,
                        )
                }.onFailure { error ->
                    if (error is ApiException && error.code in setOf("INVALID_TOKEN", "TOKEN_REVOKED")) {
                        devices.unlinkLocal()
                        mutableState.value = state.value.copy(linked = false, status = null)
                    }
                    mutableState.value = state.value.copy(backendMessage = safeMessage(error))
                }
        }

    fun loadLatestRuns() =
        viewModelScope.launch {
            if (state.value.healthState != HealthOnboardingState.READY) {
                mutableState.value = state.value.copy(healthMessage = "Сначала предоставьте доступ Health Connect")
                return@launch
            }
            mutableState.value = state.value.copy(loadingRuns = true, healthMessage = null)
            runCatching { health.latestRuns() }
                .onSuccess { search ->
                    val runs = search.runs.map { RunItem(it, mapper.map(it)) }
                    val ready = runs.count { it.mapping is RunMappingResult.Ready }
                    val errors = runs.count { (it.mapping as? RunMappingResult.Invalid)?.reason == RunSkipReason.READ_ERROR }
                    mutableState.value =
                        state.value.copy(
                            loadingRuns = false,
                            runs = runs,
                            runSearchSummary =
                                RunSearchSummary(
                                    searchedFrom = search.searchedFrom,
                                    searchedUntil = search.searchedUntil,
                                    found = runs.size,
                                    ready = ready,
                                    skipped = runs.size - ready - errors,
                                    errors = errors,
                                    nonRunning = search.nonRunningCount,
                                    pagesRead = search.pagesRead,
                                    olderRecordsExist = search.olderRecordsExist,
                                ),
                            healthMessage =
                                if (runs.isEmpty()) {
                                    if (search.olderRecordsExist) {
                                        "В выбранном периоде пробежек нет, но Health Connect содержит более старые записи вне периода поиска."
                                    } else {
                                        "Health Connect не вернул пробежек. Если Samsung Health не передал запись, добавьте ее вручную или импортируйте GPX/TCX/FIT/CSV."
                                    }
                                } else {
                                    null
                                },
                        )
                }.onFailure { error ->
                    mutableState.value =
                        state.value.copy(loadingRuns = false, healthMessage = "Не удалось прочитать данные Health Connect")
                }
        }

    fun attachRoute(
        recordId: String,
        route: ExerciseRoute?,
    ) {
        if (route == null) {
            mutableState.value = state.value.copy(healthMessage = "Доступ к маршруту не предоставлен")
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
                healthMessage = "Маршрут добавлен только к этой синхронизации",
            )
    }

    fun sync() =
        viewModelScope.launch {
            val ready = state.value.runs.mapNotNull { (it.mapping as? RunMappingResult.Ready)?.activity }
            if (!state.value.linked || ready.isEmpty()) {
                mutableState.value = state.value.copy(backendMessage = "Нет пробежек для синхронизации")
                return@launch
            }
            mutableState.value = state.value.copy(syncing = true, backendMessage = null)
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
                            backendMessage =
                                "Синхронизация: сохранено ${response.counts.saved}, " +
                                    "дубли ${response.counts.duplicate}, пропущено ${response.counts.skipped}, " +
                                    "ошибок ${response.counts.error}",
                        )
                    refreshStatus()
                }.onFailure { error ->
                    mutableState.value = state.value.copy(syncing = false, backendMessage = safeMessage(error))
                }
        }

    private fun safeMessage(error: Throwable): String =
        when (error) {
            is ApiException -> error.message ?: error.code
            else -> "Ошибка сети или backend"
        }

    private fun permissionResultMessage(permissionState: PermissionState): String =
        if (permissionState.baseGranted) {
            "Доступ к данным Health Connect предоставлен"
        } else {
            "Idaten видит не все базовые разрешения Health Connect. Проверьте список ниже и запросите доступ повторно."
        }

    class Factory(
        private val devices: DeviceRepository,
        private val health: HealthConnectSource,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = MainViewModel(devices, health) as T
    }
}
