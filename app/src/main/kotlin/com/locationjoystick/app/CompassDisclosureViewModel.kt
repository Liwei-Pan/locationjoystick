package com.locationjoystick.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.locationjoystick.core.common.constants.AppConstants
import com.locationjoystick.core.data.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Records the user's answer to the compass accessibility disclosure launched via [MainActivity]'s intent. */
@HiltViewModel
class CompassDisclosureViewModel
    @Inject
    constructor(
        private val settingsRepository: SettingsRepository,
    ) : ViewModel() {
        fun record(accepted: Boolean) {
            viewModelScope.launch { settingsRepository.recordCompassDisclosure(accepted) }
        }

        /** Marks the first-run prompt as asked without consenting; entry points still re-show it. */
        fun skip() {
            viewModelScope.launch {
                settingsRepository.setCompassDisclosureChoice(AppConstants.CompassTrackingConstants.DISCLOSURE_SKIPPED)
            }
        }
    }
