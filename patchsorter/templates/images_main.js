let DEBUG = false;
/* Variable used to hold the cound to images */
let imgCntNo = 0;
/*Variable used to hold the make_patches time in the database */
let proj_makepatches = "None";
/* Variable used to hold the embed_iteration value in the database */
let proj_embed_iteration = -2;
//Code for image selection and viewing image
let selectedImgsArr = {};
let page_limit = 0;
/* Variable to keep track of selected image objects for multi and single select */
let selectedImgsObjectSet = new Set();


function init() {
    imgCntNo =  "{{project.nImages}}";//getImageCount("{{ project.id }}");
    document.getElementById("no_of_images").innerText = imgCntNo;
    proj_makepatches = "{{project.make_patches_time}}";
    if(proj_makepatches != "None")
    {
        proj_embed_iteration = "{{project.embed_iteration}}"
    }
    updatePageButton();
    if(imgCntNo > 0)
    {
        loadRunningTimers();
        page_limit = parseInt($( "#no_of_imgs" ).val());
        initPagination(imgCntNo,page_limit);
    }
    $("#selectionCount").hide();
}

function loadRunningTimers() {
    const project_id = "{{ project.id }}";
    const completed_callback_function = updatePageButton;
    if(proj_makepatches == "None"){
        cmds_to_check = ["make_patches"];
        loadRunningJobsForProject(project_id, completed_callback_function,cmds_to_check);
    }else{
        loadRunningJobsForProject(project_id, completed_callback_function);
    }

}

function updatePageButton(){
    if (imgCntNo == 0) {
            toggleButton("make_patches",true,"'make_patches' is NOT ready to use. Please upload Images");
            toggleButton("view_embed",true,"'View Embedding' is NOT ready to use.");
        } else if(imgCntNo > 0 && proj_makepatches == "None"){
            toggleButton("viewImage",false,"View Image");
            toggleButton("viewMaskImage",false,"View Mask");
            toggleButton("make_patches",false,"'make_patches' is ready to use");
        }else if(imgCntNo > 0 && proj_makepatches != "None"){
            toggleButton("viewImage",false,"View Image");
            toggleButton("viewMaskImage",false,"View Mask");
            toggleButton("make_patches",false,"'make_patches' is ready to use");
            toggleButton("view_embed",false,"'View Embedding' is ready to use.");
            toggleButton("viewAnnotations",false,"View Annotations");
           if(proj_embed_iteration > -2){
               toggleButton("viewPredictions",false,"View Predictions");
           }
           updateProjectStatistics();
        }
}

/**
 * Update the View Embed Button Post Make_patches.
 */
function updateViewEmbedButton() {
    /* Removed the check for make_patches was not needed. */
    toggleButton("view_embed",false,"'View Embedding' is ready to use.");
    toggleButton("viewAnnotations",false,"View Annotations");
    updateProjectStatistics();
}


function make_patches() {
        addNotification("'Make Patches' Pressed.")
        // Using URL instead of string here
        let run_url = new URL("{{ url_for('api.make_patches', project_name=project.name) }}", window.location.origin)
        return loadObjectAndRetry(run_url, updateViewEmbedButton)
    }


function viewImage()
{
        for(let key in selectedImgsArr) {
            let url = "{{ url_for('html.view_image', project_name = project.name, image_id= '!!!!!') }}";
            url = url.replace(escape("!!!!!"),key);
            window.open(url);
        }
}

function viewMask()
{
        for(let key in selectedImgsArr) {
            let url = "{{ url_for('html.view_mask', project_name = project.name, image_id= '!!!!!') }}";
            url = url.replace(escape("!!!!!"),key);
            window.open(url);
   }
}


function viewAnnotations()
{
        for(let key in selectedImgsArr) {
            let url = "{{ url_for('html.get_output_image_gt', project_name = project.name, image_id= '!!!!!') }}";
            url = url.replace(escape("!!!!!"),key);
            window.open(url);
        }
}

function viewPredictions()
{
        for(let key in selectedImgsArr) {
            let url = "{{ url_for('html.get_output_image_pred', project_name = project.name, image_id= '!!!!!') }}";
            url = url.replace(escape("!!!!!"),key);
            window.open(url);
    }
}

function getParameterByName(name, url) {
    // if (!url) url = window.location.href;
    name = name.replace(/[\[\]]/g, '\\$&');
    var regex = new RegExp('[?&]' + name + '(=([^&#]*)|&|#|$)'),
        results = regex.exec(url);
    if (!results) return null;
    if (!results[2]) return '';
    return decodeURIComponent(results[2].replace(/\+/g, ' '));
}


function changelimit() {
        page_limit = parseInt($("#no_of_imgs").val());
         $('#compact-pagination').pagination('updateItemsOnPage',page_limit);
}


function initPagination(imgCntNo,no_images_disp){
    if(imgCntNo>0) {
            showNextImages(1,null);
            $('#compact-pagination').pagination({
                items: imgCntNo,
                itemsOnPage: no_images_disp,
                onPageClick: showNextImages,
                cssStyle: 'compact-theme'
            });
        }
}

function showNextImages(pgno,paginationEvent){
    //Clearing the earlier selectedImages.
    selectedImgsArr = {};
    let image_list = new URL("{{url_for('api.image',project_name=project.name)}}", window.location.origin);
        image_list.searchParams.append("image_list", 'Y');
        image_list.searchParams.append("pageNo", pgno);
        image_list.searchParams.append("pageLimit", page_limit);
        fetch(image_list).then(response => {
            return response.json();
        }).then((data) => {
                if(data){
                    display_images(data);
                }
                else{
                    addNotification("No Images Obtained.");
                }
            });
}


/** Code for the loader symbol **/
var myVar;

function myTimer() {
   myVar = setInterval(showLoadingWheel, 3000);
}
function showLoadingWheel(){
    document.getElementById("loader").style.display = "block";
}

function display_images(imgList){
    document.getElementById("loader").style.display = "none";
    document.getElementById("lbl_no_of_imgs").style.display= "block";
    document.getElementById("no_of_imgs").style.display="block";
    clearInterval(myVar);
    document.getElementById("imageSection").innerHTML = "";
    data = imgList.images;
    /** Code to construct the image gallery **/
    data.forEach(function(d,i){
        var $divResp = $('<div>',{'class':'responsive'});
            $divResp.attr('id',i);
            $divResp.appendTo($("#imageSection"));
        var $divGallery = $('<div>',{'class':'gallery'});
            $divGallery.appendTo($divResp);
        var $divImage = $('<div>');
            $divImage.attr('id',"image_id_"+d.image_id);
            $divImage.appendTo($divGallery);
        var $imageTag = $('<img>',{'class':'selected-image'});
            $imageTag.attr('id',d.image_id);
            imageUrl = "{{ url_for('api.get_image_thumb',project_name=project.name,image_name='!!!!',image_path='####')}}"
            // imageUrl = imageUrl.replace(escape("|||"),project_name);
            imageUrl = imageUrl.replace(escape("!!!!"),d.image_name);
            imageUrl = imageUrl.replace(escape("####"),d.image_path);
            $imageTag.attr('src',imageUrl);
            $imageTag.attr('height','200px')
            $imageTag.appendTo($divImage);
        var $imageDesc = $('<div>',{'class':'desc'});
            $imageDesc.html(d.image_name);
            $imageDesc.appendTo($divImage);
    });
    $("img").click(function (event) {
        if (this in selectedImgsObjectSet) {
            deselectImage(this)
        }
        else if (event.shiftKey && $(this).hasClass("selected-image")) {
            selectImage(this)
        }
        else {
            clearAllSelected();

            if ($(this).hasClass("selected-image")) {
                selectImage(this)
            }

        }
    });
}

function clearAllSelected() {
    selectedImgsObjectSet.forEach(element => {
        deselectImage(element)
    })
    selectedImgsObjectSet = new Set();
}

function selectImage(value) {
    let name = $(value).attr('id')
    $(value).css({ border: '5px dotted #000' });
    $(value).removeClass("selected-image");
    selectedImgsArr[name] = $(value).attr("src");
    selectedImgsObjectSet.add(value)
    changeButtonCount(selectedImgsArr);
}
function deselectImage(value) {
    let name = $(value).attr('id')
    $(value).addClass("selected-image");
    $(value).css({ border: 'none' });
    delete selectedImgsArr[name];
    changeButtonCount(selectedImgsArr);
}

function changeButtonCount(selectedImgsArr) {
    lengthSelected = Object.keys(selectedImgsArr).length
    if (lengthSelected === 0) {
        $('#viewImage').html(`View Image`)
        $('#viewMaskImage').html(`View Mask Image`)
        $('#viewAnnotations').html(`View Annotations`)
        $('#viewPredictions').html(`View Predictions`)
        $("#selectionCount").hide()
    }
    else if (lengthSelected === 1) {
        $('#viewImage').html(`View ${lengthSelected} Image`)
        $('#viewMaskImage').html(`View ${lengthSelected} Mask Image`)
        $('#viewAnnotations').html(`View ${lengthSelected} Annotation`)
        $('#viewPredictions').html(`View ${lengthSelected} Prediction`)
        $("#selectionCount").show()
        $("#noSelectedImages").html(`${lengthSelected} Item Selected`)

    }
    else {
        $('#viewImage').html(`View ${lengthSelected} Images`)
        $('#viewMaskImage').html(`View ${lengthSelected} Mask Images`)
        $('#viewAnnotations').html(`View ${lengthSelected} Annotations`)
        $('#viewPredictions').html(`View ${lengthSelected} Predictions`)
        $("#noSelectedImages").html(`${lengthSelected} Items Selected`)
    }
}


/**
 * Fetch Statistics No Of objects and Percent Annotated for the Project
 */
function updateProjectStatistics(){
    let run_url = new URL("{{ url_for('api.project_status', project_name=project.name) }}", window.location.origin)
    let xhr_statsjson = new XMLHttpRequest();
    xhr_statsjson.overrideMimeType("application/json");
    xhr_statsjson.open("GET", run_url, true);
    xhr_statsjson.onload = function () {
        const status_code = xhr_statsjson.status;

        switch (status_code) {
            case 200:
                updateStatistics(JSON.parse(xhr_statsjson.response));
                break;
            case 400:
                let json_output = JSON.parse(xhr_statsjson.response);
                showWindowMessage('ERROR 400: ' + json_output.error, 'HTML Error');
                break;
            default:
                showWindowMessage('ERROR ' + status_code + ': (Unknown error)', 'HTML Error');
        }
    };
    xhr_statsjson.send();
}

// /**
//  * Updates the Statistics No Of objects and Percent Annotated on the Page
//  */
// function updateStatistics(projectstats){
//     document.getElementById("no_of_objects").innerHTML = projectstats["object_count"];
//     document.getElementById("percent_of_objects_annotated").innerHTML = projectstats["percent_annotated"]+"%";
// }
