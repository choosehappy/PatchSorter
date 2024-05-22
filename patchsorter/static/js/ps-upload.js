
class UploadType {
    // https://www.sohamkamani.com/javascript/enums/
    static image = new UploadType('image')
    static mask  = new UploadType('mask' )
    static csv   = new UploadType('csv'  )
    static list  = new UploadType('list' )
    constructor(name) {
      this.name = name
    }
}
const upload_types = Object.keys(UploadType)

let project_folder = '.';
let upload_paths;
let validated_matching_filenames;
let mask_type = "MA";
let selectors;
let upload_project_name;
let upload_session;
let step_num;
let validated_filenames;
let upload_is_folder

launchUploadWizard = function() {
    initializeUploadModal()
    $('#uploadModal').modal('show')
}

initializeUploadModal = function() {

    upload_paths = {}
    upload_is_folder = {}

    mask_type = "QA";
    selectors = {
        'mask_input': {
            'value': true,
            'title': 'Upload Masks'
        },
        'csv_input': {
            'value': true,
            'title': 'Upload CSVs'
        },
        'upload_step_by_step': {
            'title': 'Approach',
            'true_text': 'Step-by-step',
            'false_text': 'File List',
        },
        'use_dropzone': {
            'value': true,
            'title': 'Choose Data Source',
            'true_text': 'Upload Files',
            'false_text': 'Load Folder',
        }
    }
    step_num = 0;

    // Set up handlers for Folder Selection method
    for (const type of upload_types) {
        upload_paths[type] = new Array()
        upload_is_folder[type] = false
    }

    // Populate the modal with an AJAX call.
    upload_project_name = $('#project_name').text();
    project_folder = './' + upload_project_name;

    // Replace the contents of the uploadModal with new HTML
    $.ajax('/upload/' + upload_project_name + '/modal/',
        {
            success: function (data, status, xhr) {
                // On success, replace the contents of the modal
                $('#uploadModal').html(data.modal);

                // Save off the session id
                upload_session = uuidv4()

                // Activate the radio buttons we just downloaded
                setupRadioButtons();
                // Activate the dropzone we just downloaded
                setupDropzones();
                // Activate the upload-folder inputs

                // enable/disable the next button as needed
                $('.upload-folder-path').keyup(tryEnableNextButton);

                // https://stackoverflow.com/a/12146864
                // (could theoretically do 'paste keyup' here to reduce code, but then the keyup has the 200ms delay which hurts the user experience)
                $('.upload-folder-path').on('paste', function() {
                    const delay_ms = 200
                    setTimeout(function() {
                        tryEnableNextButton()
                    }, delay_ms);
                })
                
                updateModal(0);
            }
        }
    );
}

$(document).ready(initializeUploadModal)

uploadCompleted = function(){
    closeUploadModal()
    location.reload()
}

closeUploadModal = function(){
    // Close the upload modal
    $('#uploadModal').modal('hide')
    initializeUploadModal()
}


cancelUpload = function(){
    // The upload modal has been closed. Hide it until the Upload Images button is clicked again. (Should we clear DZs?)
    closeUploadModal();
    resetDropzones();
    updateModal(0);
}


resetDropzones = function(){
    for (const dropzone of Object.values(dropzones)) {
        dropzone.removeAllFiles(true);
    }
}


hideShowUploadDiv = function(hiding) {
    const div_id = 'modal-input-selector-frame'
    const div = $('#' + div_id)            
    if (hiding) {
        div.hide()
    }
    else {
        div.show()
    }
}

resetUploadDivVisible = function(inputName) {
    const value = getToggleValue(inputName)
    selectors[inputName].value = value;
    hideShowUploadDiv(!value)
}

updateToggleButtons = function(inputName) {
    $("input[name='" + inputName + "']").on('change', function() {
        const value = getToggleValue(inputName)
        selectors[inputName].value = value;
        if (inputName === 'use_dropzone'){
            toggleLocalUpload();
        }
        else if (inputName.endsWith('_input')) {
            resetUploadDivVisible(inputName)
        }
        tryEnableNextButton();
    })
}


getToggleValue = function (inputName) {
    const selected = $("input[name='" + inputName + "']:checked");
    const value = selected !== undefined && selected.val() === "1";
    console.log('Toggle value = ', value);
    return value;
}


setupRadioButtons = function (){
    // Configure all the radio buttons to update their assigned variables

    // Mask Type
    $("input[name='mask_type']").on('change', function() {
        let selected = $("input[name='mask_type']:checked");
        if (selected !== undefined) {
            mask_type = selected.val();
        }
    });

    const selector_keys = Object.keys(selectors);
    for (const key of selector_keys){
        makeRadioDiv(key);
        updateToggleButtons(key);
    }
};

makeRadioDiv = function(key){
    const selector = selectors[key];
    const parent = $('#selector-' + key);

    let form = $('<form id="selector-' + key + '-form"></form>');
    let title = $('<h3>' + selectors[key].title + '</h3>');
    form.append(title);

    let radio_div = $('<div class="radio" id="selector-' + key + '-radio">');
    let true_button = makeRadioToggleButton(key, true);
    let false_button = makeRadioToggleButton(key, false);
    radio_div.append(true_button);
    radio_div.append(false_button);
    form.append(radio_div);
    parent.append(form);
}


makeRadioToggleButton = function(key, is_true){
    // Construct the button values
    const button_value = (+ is_true).toString();
    let button_text;
    if (is_true){
        button_text = selectors[key].true_text || 'Yes';
    } else {
        button_text = selectors[key].false_text || 'No';
    }
    const button_id = 'selector-' + key + '-radio' + button_value;

    $(button_id).addEve
    // Then start building the HTML
    let wrapper = $('<label></label>');
    let button = $('<input type="radio" name="' + key + '" id="' + button_id + '" value="' + button_value + '">');
    if (selectors[key].value === is_true){
        button.prop('checked', true);
    }
    wrapper.append(button);
    wrapper.append(button_text);
    return wrapper;
}

setRadioEnabled = function(key, disable) {
    const frame = $('#modal-input-selector-frame')
    if (disable) {
        frame.hide()
    }
    else {
        frame.show()
    }
}

let dropzones = {};
let upload_processing = false
setupDropzones = function (){
    for (const zone_type of upload_types) {
        
        const dropzone = $('#upload-' + zone_type + '-dropzone')
        dropzone.dropzone({
            url: '/upload/' + upload_project_name + '/' + upload_session + '/' + zone_type + '/',
            acceptedFiles: (zone_type == 'mask' || zone_type == 'image') ? 'image/*' : '.csv',
            uploadMultiple: zone_type != 'list',
            maxFiles: (zone_type == 'list') ? 1 : null,
            autoProcessQueue: false,
            addRemoveLinks: true,
            init: function() {
                dzClosure = this; // Makes sure that 'this' is understood inside the functions below.

                // for Dropzone to process the queue (instead of default form behavior):
                document.getElementById("modal-next-button").addEventListener("click", function(e) {
                    // Make sure that the form isn't actually being sent.
                    e.preventDefault();
                    e.stopPropagation();
                    console.log('Dropzone files submitted.');
                });

                // Make a note whenever a file is added
                this.on("addedfile", function(file) {
                    upload_paths[zone_type].push(file.name);
                    tryEnableNextButton()
                });

                this.on('removedfile', function(file) {
                    if (upload_paths[zone_type].includes(file.name)) {
                        upload_paths[zone_type].splice(upload_paths[zone_type].indexOf(file.name),1)
                    }
                    tryEnableNextButton()
                });

                //send all the form data along with the files:
                this.on("sendingmultiple", function(data, xhr, formData) {
                    //console.log('Sending multiple.');
                });
                this.on("totaluploadprogress", function(progress) {
                    const counts = dzGetCounts(this);
                    // console.log(counts);
                    // console.log(progress);
                    const total_progress = (counts['files'] - counts['queued'] - 1 + progress / 100) / counts['files'];
                    const type = this.element.dataset.type;
                    if (total_progress >= 0) {
                        showProgress(total_progress, type);
                    }
                });
                this.on("processing", function(file) {
                    upload_processing = true
                    this.options.autoProcessQueue = true
                });
                this.on("success", function(file, response) {
                    if (zone_type == 'list') {
                        console.log('List uploaded.')
                        showReview()
                    }
                });
                this.on("queuecomplete", function() {
                    if (upload_processing) {
                        this.options.autoProcessQueue = false
                        upload_processing = false
                        dzHandleQueueComplete(zone_type)
                    }
                })
                this.on('error', function(file, message) {
                    addNotification('Error uploading ' + file.name + ': ' + message)
                    this.removeFile(file)
                })
            }
        })
        dropzones[zone_type] = dropzone[0].dropzone;
    }
}


dzHandleAddedFile = function(dropzone){
    // When a file is added to a dropzone, validate to see if the Next button should be activated
    const type = dropzone.element.dataset.type;
    tryEnableNextButton();
}


disableDropzone = function(){
    const type = getCurrentUploadType()
    const dropzone = $("#upload-" + type.toLowerCase() + "-form");
    dropzone.children().prop('disabled',true);
    dropzone.fadeTo(500, 0.2);
}

getCurrentUploadType = function(){
    // Use the saved step_num to find the tag for the current upload type
    return upload_types[step_num - 1]
}

isReadyToUpload = function(){
    const type = getCurrentUploadType();
    if (selectors['use_dropzone'].value){
        // Make sure there are files in the dropzone to upload
        const dropzone = dropzones[type];
        return dropzone.files.length > 0;
    } else {
        // Make sure there's text in the upload-path input
        const path_input = $('#' + type.toLowerCase() + '-folder-path')
        const path = path_input.val()
        return path !== ''
    }
}

toggleLocalUpload = function() {
    // If the current step's uploads are Local, show the Dropzone, otherwise show the path input form
    const dz_frame = $('#modal-dropzones');
    const path_frame = $('#modal-upload-paths');
    const type = getCurrentUploadType()
    const use_dropzone = selectors["use_dropzone"].value
    upload_is_folder[type] = !use_dropzone
    if (use_dropzone) {
        dz_frame.show()
        path_frame.hide()
    } else {
        dz_frame.hide()
        path_frame.show()
        if (type in dropzones) {
            dropzones[type].removeAllFiles()
        }
    }
}

resetApproach = function() {
    $('#description-step_by_step').hide()
    $('#description-file_list').hide()
    show_steps = []
    showUploadWizardTabs(show_steps)
}
beginStepByStep = function() {
    $('#description-step_by_step').show()
    show_steps = [1,2,3,5,6]
    showUploadWizardTabs(show_steps)
}
beginFileList = function() {
    $('#description-file_list').show()
    show_steps = [4,5,6]
    showUploadWizardTabs(show_steps)
}
showUploadWizardTabs = function(which_steps) {
    for (let step = 1; step <= 6; step++) {
        element_id = '#modal-step-label-' + step.toString()
        $(element_id).hide()
    }
    for (step of which_steps) {
        element_id = '#modal-step-label-' + step.toString()
        $(element_id).show()
    }
}


tryEnableNextButton = function() {
    // For the current step, validate that there are enough files in the dropzone queue to proceed
    const next_button = $('#modal-next-button')
    disable_nav_button(next_button)
    if (step_num === 0){
        // Set the button based on the chosen approach
        resetApproach()
        if (selectors['upload_step_by_step'].value){
            enable_nav_button(next_button, selectStepByStepMethod)
            beginStepByStep()
        } else if (selectors['upload_step_by_step'].value === false) {    // It starts out undefined
            enable_nav_button(next_button, selectFileListMethod);
            beginFileList()
        }
    } else if (step_num === 1 && isReadyToUpload()){
        // Upload images. isReadyToUpload() evaluates between dropzone and server path
        enable_nav_button(next_button, showMasksUpload);
    } else if (step_num === 2 && (isReadyToUpload() || !selectors['mask_input'].value)){
        // Upload masks.
        enable_nav_button(next_button, showCSVsUpload);
    } else if (step_num === 3 && (isReadyToUpload() || !selectors['csv_input'].value)){
        // Upload CSVs.
        enable_nav_button(next_button, showReview);
    } else if (step_num === 4 && isReadyToUpload()){
        // Upload a single file-list.
        enable_nav_button(next_button, prepareListForReview);
    } else if (step_num === 5) {
        // fetch reviewed filenames
        if (validated_matching_filenames) { // todo: clear this variable when going back from the review pane
            enable_nav_button(next_button, startUploadAndProcessing)
        }
    } else if (step_num === 6){
        // After the upload has completed, activate the "Complete" button
        enable_nav_button(next_button, uploadCompleted);
    }
}

startUploadAndProcessing = function() {
    const next_button = $('#modal-next-button')
    disable_nav_button(next_button)
    disableBackButton()
    const cancel_button = $('')

    if (selectors['upload_step_by_step'].value) {
        // start the upload process
        uploadFiles()
    }
    else {
        // immediate start processing a file list
        processRemoteFiles()
    }
}

dzHandleQueueComplete = function(zone_type){

    showProgress(1, zone_type)

    for (const type in dropzones){
        const dropzone = dropzones[type];
        if (dropzone.getQueuedFiles().length > 0){
            console.log('Upload complete. Uploading ' + type + '.')
            dropzone.processQueue()
            return type
        }
    }

    // If we didn't already return, there's nothing left to upload. Show progress complete on any excluded upload types
    const input_types = [UploadType.mask, UploadType.csv];
    for (const type of input_types){
        const input_type = type.name
        console.log('Checking input for ' + input_type)
        if (selectors[input_type.toLowerCase() + '_input'].value === false) {
            console.log(input_type + ' omitted. Showing 100%')
            showProgress(1, input_type)
        }
    }

    console.log('Upload complete. Requesting server handling.')
    if (zone_type != UploadType.list.name) {
        processRemoteFiles()
    }
}

dzGetCounts = function (myDropzone){
    let counts = {};
    // To access all files count
    counts['files'] = myDropzone.files.length
    // To access only accepted files count
    counts['accepted'] = myDropzone.getAcceptedFiles().length
    // To access all rejected files count
    counts['rejected'] = myDropzone.getRejectedFiles().length
    // To access all queued files count
    counts['queued'] = myDropzone.getQueuedFiles().length
    // To access all uploading files count
    counts['uploading'] = myDropzone.getUploadingFiles().length
    return counts;
};

// Steps of the upload modal:
let steps = {
    0: {
        'title': 'Upload Method',
        'details': 'Choose a method to upload your data. <strong>Step-by-step</strong> will ask you to upload all your scan images first, then your masks, then your CSV labels. <strong>File List (CSV)</strong> will let you upload a single file list (CSV) describing the locations of all your files.',
        'show': {
            'selector-upload_step_by_step-form': true,
            'modal-file-upload-frame': false,   // If the upload-frame is hidden, the mask and csv sub-forms are also hidden.
            'modal-review-data-frame': false,
            'modal-upload-progress-frame': false,
            'modal-complete-frame': false,
            'modal-cancel-button': true,
            'approach-descriptions': true
        }
    },
    1: {
        'title': 'Upload Scan Images',
        'details': 'Select your images and drop them in the frame below (or click to browse). Upload only scan images at this step.',
        'show': {
            'selector-upload_step_by_step-form': false,
            'modal-file-upload-frame': true,
            'selector-mask_input-form': false,
            'selector-mask_type-form': false,
            'selector-csv_input-form': false,
            'selector-use_dropzone-form': true,
            'upload-image-form': true,
            'upload-path-input-image': true,
            'upload-mask-form': false,
            'upload-path-input-mask': false,
            'upload-csv-form': false,
            'upload-path-input-csv': false,
            'upload-list-form': false,
            'upload-path-input-filelist': false,
            'modal-review-data-frame': false,
            'modal-upload-progress-frame': false,
            'modal-complete-frame': false,
            'modal-cancel-button': true,
            'approach-descriptions': false
        }
    },
    2: {
        'title': 'Upload Masks',
        'details': 'Select your mask source, then upload the images below.',
        'show': {
            'selector-upload_step_by_step-form': false,
            'modal-file-upload-frame': true,
            'selector-mask_input-form': true,
            'selector-mask_type-form': true,
            'selector-csv_input-form': false,
            'selector-use_dropzone-form': true,
            'approach-descriptions': false,
            'upload-image-form': false,
            'upload-path-input-image': false,
            'upload-mask-form': true,
            'upload-path-input-mask': true,
            'upload-csv-form': false,
            'upload-path-input-csv': false,
            'upload-list-form': false,
            'upload-path-input-filelist': false,
            'modal-review-data-frame': false,
            'modal-upload-progress-frame': false,
            'modal-complete-frame': false,
            'modal-cancel-button': true
        }
    },
    3: {
        'title': 'Upload CSVs',
        'details': 'Do you have CSVs with labeled details for every image uploaded earlier?',
        'next_text': 'Review',
        'show': {
            'selector-upload_step_by_step-form': false,
            'approach-descriptions': false,
            'modal-file-upload-frame': true,
            'selector-mask_input-form': false,
            'selector-mask_type-form': false,
            'selector-csv_input-form': true,
            'selector-use_dropzone-form': true,
            'upload-image-form': false,
            'upload-path-input-image': false,
            'upload-mask-form': false,
            'upload-path-input-mask': false,
            'upload-csv-form': true,
            'upload-path-input-csv': true,
            'upload-list-form': false,
            'upload-path-input-filelist': false,
            'modal-review-data-frame': false,
            'modal-upload-progress-frame': false,
            'modal-complete-frame': false,
            'modal-cancel-button': true
        }
    },
    4: {
        'title': 'File List',
        'details': 'Instructions: Select a comma-separated file (*.csv) in the dropzone below. Each row should contain exactly 3 columns: image filename, mask filename, csv filename (in that order). There should be no header row. Each value must be an absolute path pointing to an existing file on the machine hosting this app. Note: The machine hosting this app may not be the same machine you are browsing on right now - if it is being hosted on a remote server, the file paths must point to files already on that server.',
        'next_text': 'Review',
        'show': {
            'selector-upload_step_by_step-form': false,
            'approach-descriptions': false,
            'modal-file-upload-frame': true,
            'selector-mask_input-form': false,
            'selector-mask_type-form': true,
            'selector-csv_input-form': false,
            'selector-use_dropzone-form': false,
            'upload-image-form': false,
            'upload-path-input-image': false,
            'upload-mask-form': false,
            'upload-path-input-mask': false,
            'upload-csv-form': false,
            'upload-path-input-csv': false,
            'upload-list-form': true,
            'upload-path-input-filelist': true,
            'modal-review-data-frame': false,
            'modal-upload-progress-frame': false,
            'modal-complete-frame': false,
            'modal-cancel-button': true
        }
    },
    5: {
        'title': 'Review Data',
        'next_text': 'Process',
        'show': {
            'selector-upload_step_by_step-form': false,
            'approach-descriptions': false,
            'selector-use_dropzone-form': false,
            'modal-file-upload-frame': false,
            'modal-review-data-frame': true,
            'modal-upload-progress-frame': false,
            'modal-complete-frame': false,
            'modal-cancel-button': false
        }
    },
    6: {
        'title': 'Upload Complete',
        'next_text': 'Close',
        'show': {
            'selector-upload_step_by_step-form': false,
            'approach-descriptions': false,
            'selector-use_dropzone-form': false,
            'modal-file-upload-frame': false,
            'modal-review-data-frame': true,
            'modal-upload-progress-frame': true,
            'modal-review-data-table': true,
            'modal-complete-frame': true,
            'modal-cancel-button': false
        }
    },
}

resetSelectors = function() {

    let step_key = false;
    if (step_num === 2) {
        step_key = UploadType.mask
    } else if (step_num === 3){
        step_key = UploadType.csv
    }

    if (step_key) {
        resetUploadDivVisible(step_key.name + '_input')
    } else {
        hideShowUploadDiv(false)
    }
    
}

updateModal = function(to_step){
    // Update the upload modal to show the next step in the process
    let previous_step = step_num;
    if (to_step === undefined){
        step_num = previous_step + 1;
    } else {
        step_num = to_step;
    }

    toggleLocalUpload()

    // Update the step indicator at the top of the frame
    changeStepIndicator(previous_step, step_num);

    // Show and hide frames in the modal based on the current step
    configureHiddenFrames();

    // And finally hook up navigation functions to the navigation buttons
    configureNavButtons();

    // hide or show the appropriate div for this step
    resetSelectors();
}

configureHiddenFrames = function() {
    // Hide/show frames in the upload modal depending on the current step
    for (const [key, value] of Object.entries(steps[step_num].show)) {
        const frame = $('#' + key);
        if (value) {
            frame.show();
        }
        else {
            frame.hide();
        }
    }

    // Update the next button text if specified
    const next_button = $('#modal-next-button');
    const next_text = steps[step_num].next_text;
    if (next_text){
        next_button.text(next_text)
    } else {
        next_button.text('Next >')
    }

    // And update the descriptive text if we have any
    $('#upload-step-title').text(steps[step_num].title);
    $('#upload-step-details').text(steps[step_num].details);
}

showProgressBar = function(){
    $('#modal-progress-frame').show();
}

disableBackButton = function() {
    const back_button = $('#modal-back-button');
    disable_nav_button(back_button)
}
configureNavButtons = function() {
    // Set up the Back/Next buttons in the modal based on the current step
    console.log('Step num: ' + step_num);
    const back_button = $('#modal-back-button');
    const next_button = $('#modal-next-button');
    disable_nav_button(next_button);

    if (step_num === 0) {
        disableBackButton()
    } else if (step_num === 1) {
        enable_nav_button(back_button, resetUploadMethod);
    } else if (step_num === 2) {
        enable_nav_button(back_button, selectStepByStepMethod);
    } else if (step_num === 3) {
        enable_nav_button(back_button, showMasksUpload);
    } else if (step_num === 4) {
        enable_nav_button(back_button, resetUploadMethod);
    } else if (step_num === 5) {
        disableBackButton()
        if (validated_matching_filenames) {
            if (selectors['upload_step_by_step'].value) {
                enable_nav_button(back_button, showCSVsUpload);
            } else {
                enable_nav_button(back_button, selectFileListMethod);
            }
        }
    } else if (step_num === 6) {
        disableBackButton()
        enable_nav_button(next_button, cancelUpload);
    }
    tryEnableNextButton();
}


disable_nav_button = function(button) {
    // Disable a nav button (Back/Next) and clear any click handlers
    button.prop('disabled', true);
    button.off('click');
}


enable_nav_button = function(button, action) {
    // Enable a nav button (Back/Next) and assign the handler action
    button.prop('disabled', false);
    button.off('click');
    button.on('click', action);
}


changeStepIndicator = function(from_step, to_step) {
    // Save step information to the modal
    $('#uploadModalLabel').data('step-num', to_step);

    // Change the CSS styling of the step-label indicators at the top of the modal to indicate current step
    let from_step_label = $('#modal-step-label-' + from_step);
    let to_step_label = $('#modal-step-label-' + to_step);

    const css_selected_classes = ['bg-primary', 'text-primary']
    const css_deselected_classes = ['bg-info', 'text-muted']

    for (let step = 0; step <= 6; step++) {
        const tab_element = $('#modal-step-label-' + step)
        for (const css_class of css_deselected_classes) {
            if (step == to_step) {
                tab_element.removeClass(css_class)
            }
            else {
                tab_element.addClass(css_class)
            }
        }
        for (const css_class of css_selected_classes) {
            if (step == to_step) {
                tab_element.addClass(css_class)
            }
            else {
                tab_element.removeClass(css_class)
            }
        }
    }
}


resetUploadMethod = function(){
    // From step 1 or 4, go back to step 0
    selectors['upload_step_by_step'].value = undefined;

    resetDropzones()

    // Clear the radio selectors
    $("input[name='upload_step_by_step']").prop('checked', false);
    updateModal(0);
};


selectStepByStepMethod = function(){
    // Hide the method-selection buttons from step 0, and show the file-upload panel for step 1
    selectors['upload_step_by_step'].value = true;
    updateModal(1);
};


showMasksUpload = function(){
    // Reconfigure the Images upload panel from step 1 or the labels upload panel from step 3 for step 2
    updateModal(2)
};


showCSVsUpload = function(){
    // Reconfigure the masks upload panel from step 2 or the review panel from step 5 for step 3
    updateModal(3)
};


selectFileListMethod = function(){
    // Hide the method-selection buttons from step 0, and show the file-upload panel for step 4
    selectors['upload_step_by_step'].value = false;
    updateModal(4);
};

showUploadComplete = function(data){
    showProgress(1, 'finalize')
    validated_filenames = data
    showReviewResults()
    updateModal(6)
}

makeResultsRow = function(image_info){
    // Given an uploaded image, generate a results row for the report
    console.log(image_info);
    const color_code = ('error' in image_info ? 'red' : 'green')
    
    let column_names = upload_types.slice(0,3)
    column_names.push('error', 'status')

    let row = '<tr class="' + color_code + '">';

    for (const column_name of column_names) {
        let row_data = (column_name in image_info ? image_info[column_name] : '')
        row_data = row_data.replace( /(<([^>]+)>)/ig, '')
        row += '<td>' + row_data + '</td>'
    }

    row += '</tr>';

    return row
}


getUploadPaths = function(){
    // Get the file uploads from our dropzones or the remote server paths from our path inputs to validate by API
    let paths = {};
    for (const type of upload_types){
        paths[type] = unpackUploadPaths(type);
        paths[type + '_is_folder'] = upload_is_folder[type]
    }

    return paths;
}


unpackUploadPaths = function(type){
    if (type === UploadType.image.name || type === UploadType.list.name || getToggleValue(type + '_input')) {
        // we always include this
        const is_dropzone = upload_paths[type].length > 0
        if (is_dropzone) {
            return Array.from(upload_paths[type])
        }
        else {
            const path_input = $('#' + type.toLowerCase() + '-folder-path');
            return path_input.val();
        }
    }
    else {
        return ''
    }
}


getReviewTableID = function(){
    return '#modal-review-data-table'
}

clearReviewResults = function(){
    const table_id = getReviewTableID()
    const table = $(table_id)
    $(table_id + ' tr').remove()
    table.append('<tr><th>Image</th> <th>Mask</th> <th>CSV</th> <th>Error</th> <th>Status</th> </tr>')
}

showReviewResults = function(){

    clearReviewResults()
    const table = $(getReviewTableID())

    // add the rows
    data = validated_filenames
    validated_matching_filenames = data['paths']
    for (const path of validated_matching_filenames) {
        console.log(path);
        const row = makeResultsRow(path)
        table.append(row)
    }

    configureNavButtons()

    // check the errors
    const error_count = data['errors']
    console.log('error_count', error_count)
    const error_div = $('#modal-review-error-message')
    if (error_count > 0 || validated_matching_filenames.length == 0) {
        const next_button = $('#modal-next-button');
        disable_nav_button(next_button);
        error_div.show()
    }
    else {
        error_div.hide()
        tryEnableNextButton()
    }
}

prepareListForReview = function(){
    dropzones['list'].processQueue()
}

// regularly check progress and update the progress bar. returns an id you can pass to clearInterval(id)
monitor_progress = function(progress_label) {
    showProgress(0, progress_label)

    // start a timer to check on progress
    const check_progress_milliseconds = 200
    const progress_interval_id = setInterval(function () {

        const url = '/upload/' + upload_session + '/progress/'
        fetch(url)
            .then(response => response.json())
            .then(data => showProgress(data['progress'], progress_label));

    }, check_progress_milliseconds)
    return progress_interval_id
}

stop_monitoring_progress = function(progress_label, interval_id) {
    clearInterval(interval_id)

    // ensure the progress updating is cleared and finished
    setTimeout(function() {
        showProgress(1, progress_label)
      }, 500)
}

showReview = function(){
    // Show the progress frames, fetch the list of local files to upload, and push them all to the server

    // clear previous results
    validated_filenames = null
    validated_matching_filenames = null
    clearReviewResults()
    updateModal(5)

    // reset progress to 0
    const progress_label = 'Matching Filenames'
    const progress_interval_id = monitor_progress(progress_label)

    const url = '/upload/' + upload_project_name + '/' + upload_session + '/validate/'
    postData(url, getUploadPaths())
    .then(data => {
        console.log("Validation successful!");
        console.log(data);
        validated_filenames = data
        showReviewResults()
        stop_monitoring_progress(progress_label, progress_interval_id)        
    })
}

uploadFiles = function(){
    clearReviewResults()

    // Show the progress frames, fetch the list of local files to upload, and push them all to the server
    if (step_num === 4){
        // We came here via the file-list method, and should process that dropzone
        dropzones['list'].processQueue();

        // TODO: Read the CSV stored in dropzones.FileList, and sort the files described therein into the other DZs
        //       Once that's finished, call processUploadStepByStep() to step through them all
    } else {
        // We came here via the step-by-step method, and should start the process by uploading the images from step 1
        processUploadsStepByStep();
    }
};

processUploadsStepByStep = function(){
    clearReviewResults()

    // Each of the Images, Masks, and CSVs dropzones has an onqueuecomplete event that cascades through all uploads
    for (const [type, dropzone] of Object.entries(dropzones)) {
        if (dropzone.getQueuedFiles().length > 0){
            dropzone.processQueue()
            return
        }
        else {
            showProgress(1, type)
        }
    }
    
    // if we reached here, none of the dropzones had files, and we need to process queue
    processRemoteFiles()

}

const upload_progress_steps = [UploadType.image.name, UploadType.mask.name, UploadType.csv.name, 'finalize']
showProgress = function(step_progress, step){
    // Display the current progress of the active operation
    step_index = upload_progress_steps.indexOf(step);
    if (step_index === -1){
        // The initial FileList upload won't be shown on the progress bar, but subsequent Images, Masks, and CSVs will
        step_index = 0
        step_share = 100
    }
    else {
        step_share = Math.floor(100 / upload_progress_steps.length);
    }
    const percentage = Math.floor(step_index * step_share + step_progress * step_share);

    const label = step + ': ' + percentage + '%'

    console.log('Progress: ' + percentage + '%');
    let progress_bar = $('#uploadProgress');
    if (progress_bar === undefined){
        // The progress dialog has been closed, stop asking for updates
        return;
    }

    showProgressBar();
    progress_bar.attr('aria-valuenow', percentage);
    progress_bar.attr('style', 'width: ' + percentage + '%;');
    progress_bar.html(label);
};


processRemoteFiles = function(){
    clearReviewResults()

    const progress_label = 'finalize'
    const progress_interval_id = monitor_progress(progress_label)

    const url = '/upload/' + upload_project_name + '/' + upload_session + '/process/'
    let data = validated_filenames
    data['mask_type'] = mask_type
    postData(url, data)
    .then(output => {
        showUploadComplete(output)
        stop_monitoring_progress(progress_label, progress_interval_id)
    })
}
