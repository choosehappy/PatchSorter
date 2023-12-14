var contextPatchSize ='{{context_patch_size}}';
var patchSize = '{{patch_size}}'
var searchKey = "";
var embeddingCnt = 0;
var gridData;
// var patchImgData;
let pageLimit = 0;
/**
 * Initializes the grid plot with pagination first
 * @param count -- Count of patches(embeddings)
 * @param key -- Unique Identifier for the data.
 */
function initGrid(count,key){
    pageLimit = parseInt($( "#no_of_patch" ).val());
    if(DEBUG){console.log("initPagination"+pageLimit);}
    var no_of_page = Math.ceil(count/pageLimit);
    searchKey = key;
    embeddingCnt=count;
    if(DEBUG){console.log("Init search Key"+searchKey);}
    initPagination(embeddingCnt);
}

/**
 * Creates the grids with all the patch images obtained from a lasso polygon.
 * @param selectedData -- contains all the patch data for a particular page.
 * @param image_data -- contains all the image_data for the respective patches.
 */
// function plotgrid(selectedData,image_data){
function plotgrid(selectedData){
    var init_gridSortBy = parseInt($("input[name='grid_sortby']:checked").val());
    // sort selected Patch data.
    selectedData.sort(function (x, y) {
        return x[init_gridSortBy] - y[init_gridSortBy];
    });
    if(DEBUG) {console.table(selectedData);}
    //Border is based on the predictions
    d3.select("#grid").remove();
    gridClass = "grid"+patchSize;
    const grid_plt = d3.select("#gridChart").append("div")
        .attr("id", "grid")
        .attr("class", gridClass)
        .classed("grid",true)
        .on("contextmenu", function () {
            d3.event.preventDefault();
        });

    var patch_imgContainer = grid_plt.selectAll("div")
                        .data(selectedData, function(d,i){return d[0];})
                        .enter()
                        .append("div")
                        .attr("id",function (d,i) { return "patch_imgid_"+d[0];})
                        .attr("class",function (d,i) { return "pred_border_"+d[4];})
                        .attr("text-align","center")
                        .classed("patch_unselected",true)
                        .classed("patch",true)
                        .attr("data-gtname",function (d,i) { return d[3];})
                        .attr("data-predname",function (d,i) { return d[4];})
                        .attr("data-predscore",function (d,i) { return d[5];})
                        .on("contextmenu", function() {
                            d3.event.preventDefault();
                        });

    patch_imgContainer.selectAll("img")
                .data(function(d,i){return [d];})
                .enter()
                .append("img")
                .attr("id",function(d, i) { return "patchid_"+d[0]})
                .attr("class",function(d, i) { return "labelp_"+d[3]})
                .classed("imgpatch_unselected",true)
                .attr("src",function(d, i) {
                        let patch_url = "{{ url_for('api.patch_image', project_name=project.name, patch_id='!!!!!') }}"
                        patch_url = patch_url.replace(escape("!!!!!"),d[0]);
                        return patch_url;
                        // return getImage(d[0])
                })
                .on("contextmenu", function(d, i) {
                    d3.event.preventDefault();
                    showContextMenu(d);
                });

    // function getImage(id){
    //     return "data:image/png;base64,"+image_data[id]
    // }
// This part of the code makes the plot selectable.
    $("#grid").selectable({
        selected: function (event, ui) {

           d3.select("#action_div").selectAll("*").remove();
            labelClass = "labelp_"+$(ui.selected).data("gtname");
            $(ui.selected).addClass('patch_selected');
            $(ui.selected).children().addClass('imgpatch_selected');
            $(ui.selected).children().addClass('ui-selected');
            $(ui.selected).children().removeClass(labelClass);
            $(ui.selected).children().removeClass('imgpatch_unselected');
            $(ui.selected).removeClass('patch_unselected');
        },
        unselected: function (event, ui) {
            labelClass = "labelp_"+$(ui.unselected).data("gtname");
            $(ui.unselected).children().addClass(labelClass);
            $(ui.unselected).children().addClass('imgpatch_unselected');
            $(ui.unselected).addClass('patch_unselected');
            $(ui.unselected).removeClass('patch_selected');
            $(ui.unselected).children().removeClass('imgpatch_selected');
            $(ui.unselected).children().removeClass('ui-selected');
            $(ui.unselected).children().removeClass('patch_selected');
        }
    });
     setLabelOptions(false);
    //Removes the context Patch once the user moves over the scatter plot.
    d3.select("#scatterChart").on('mouseover',function(){
        d3.select("#action_div").selectAll("*").remove();
    });
    currentCursor = document.getElementById("graphView").style.cursor;
    if(currentCursor == "wait"){
        readyCursor();
    }

}


var showContextMenu = function(d) {
    let patch_id = d[0];
    let context_url = "{{ url_for('api.patch_context_image', project_name = project.name, patch_id= '!!!!!') }}";
    context_url = context_url.replace(escape("!!!!!"), patch_id);
    let context_patch_name = "context_"+patch_id;
    if (d3.event.pageX || d3.event.pageY) {
        var x = d3.event.pageX;
        var y = d3.event.pageY;
    } else if (d3.event.clientX || d3.event.clientY) {
        var x = d3.event.clientX + document.body.scrollLeft + document.documentElement.scrollLeft;
        var y = d3.event.clientY + document.body.scrollTop + document.documentElement.scrollTop;
    }
    d3.select("#action_div").selectAll("*").remove();
    var actionDiv =  d3.select('#action_div')
                    .style('position', 'absolute')
                    .style('left', x + 'px')
                    .style('top', y + 'px')
                    .style('display', 'block')
    actionDiv.append('img')
        .attr("id","img_"+parseInt(d[0]))
             .attr("src",new URL(context_url, window.location.origin))
            .attr("x", x)
        .attr("y",y)
        .attr("width",parseInt(contextPatchSize))
        .attr("height",parseInt(contextPatchSize))
        .style('border','solid')
        .on("contextmenu",function(d, i) {
            d3.event.preventDefault();
            d3.select("#action_div").selectAll("*").remove();
        })
        .on('click',function(d,i){
            d3.select("#action_div").selectAll("*").remove();
        });

}


function update_label_names(){
    loadShortCuts(true);
    var Cnt = $("#Labelcnt").val();
    var labelNames = []
    for(i=0;i<Cnt;i++){
        label = {}
        label["id"]=$("#Label_row_id_"+i).val()
        label["label_id"]=i;
        label["label_name"]=$("#Label_id_"+i).val();
        labelNames.push(label);
    }
    data = JSON.stringify(labelNames);
    let xhr = new XMLHttpRequest();
       let run_url = "{{ url_for('api.label_names', project_name = project.name, labels= '') }}" + data;
                // let run_url = "api/"+projectname+"/image_folder/?file_path=" + filepath;
                // $dialog.dialog('close');
                xhr.onreadystatechange = function () {
                     $("#dialog-form").dialog('close');
                    if(xhr.readyState === XMLHttpRequest.DONE) {
                        var status = xhr.status;
                        if(status === 200){
                            loadGridPlotButtons(false);
                        }
                        else if(status === 400){
                            showWindowMessage('ERROR 400: ' + json_output.error, 'HTML Error');
                         }
                        else{
                            showWindowMessage('ERROR: Labels not updated.', 'HTML Error');
                        }
                    }

        };
        xhr.open("PUT", run_url, true);
        xhr.send();

}


/*code for patch selection
* Obtains all the selected patches and collects the patch id and removes
* the old label class to reset the border color
* */

function getSelectedPatch(){
    var selectPatch = {};
    d3.selectAll(".patch_selected").each(function(d) {
        var imgSel =  d3.select(this);
        var classes = imgSel.attr("class");
        var patch_id = d[0];
        var orig_pred = d[4];
        imgSel.classed("labelp_"+orig_pred,false);
        selectPatch[patch_id]=orig_pred;
    })
    return selectPatch;
}


/*Method invoked to update the labels for the images.*/
function updateGroundTruth()
{
     addNotification("'Apply Labels' Pressed.");
     waitCursor();
     toggleScatterPlotButtons(true,"updateGroundTruth");

     selectedPatchDict = getSelectedPatch();
     var ground_truth = d3.select("#labelSelect").property("value");
     patch_ids = [];
     for(key in selectedPatchDict) {
         patch_ids.push(key);
     }
     if(patch_ids.length == 0){
         showWindowMessage('No Patches Selected', 'HTML Error');
          readyCursor();
     }else {
         var run_url = "{{ url_for('api.patch_data', project_name=project.name, patch_id = '!!!!!', gt='###' ) }}"
         run_url = run_url.replace(escape("!!!!!"), patch_ids);
         run_url = run_url.replace(escape("###"), ground_truth);
         let xhr_updategtjson = new XMLHttpRequest();
         xhr_updategtjson.overrideMimeType("application/json");
         xhr_updategtjson.open("PUT", run_url, true);
         xhr_updategtjson.onload = function () {
             const status_code = xhr_updategtjson.status;
             switch (status_code) {
                 case 200:
                     updategrid(JSON.parse(xhr_updategtjson.response));
                     addNotification("Project Ground Truth updated ");
                     break;
                 case 400:
                     let json_output = JSON.parse(xhr_updategtjson.response);
                     showWindowMessage('ERROR 400: ' + json_output.error, 'HTML Error');
                     break;
                 default:
                     showWindowMessage('ERROR ' + status_code + ': (Unknown error)', 'HTML Error');
             }
         };
         xhr_updategtjson.send();
     }
}


//Update the plot grid once the labels are updated.
function updategrid(patch_data)
{
    var patch_ids =  patch_data["patch_id"].split(',');
    for(i=0; i< patch_ids.length; i++ ){
        for(j=0; j< gridData.length; j++){
            if(gridData[j][0] == patch_ids[i]){
                gridData[j][3] = patch_data["ground_truth"];
            }
        }
    }
    updateStatistics(patch_data);
    // document.getElementById("percent_of_objects_annotated").innerHTML = patch_data["percent_annotated"]+"%";
    curr_action = "labelling"
    // initialize_plots(init_status=false,action_type=curr_action);
    updateCurrentPlot(patch_ids,patch_data["ground_truth"]);
    $('#filter_patch').val("All").change();
    // plotgrid(gridData,patchImgData);
    plotgrid(gridData);

}



//select all patches
function selectall()
{
    d3.selectAll(".imgpatch_unselected").each(function(d){
        labelBorder =  "labelp_"+d[3];
        d3.select(this).classed("ui-selected",true);
        d3.select(this).classed(labelBorder,false);
        d3.select(this).classed("imgpatch_selected",true);
        d3.select(this).classed("imgpatch_unselected",false);
    })
    d3.selectAll(".patch_unselected").classed("ui-selected",true);
    d3.selectAll(".patch_unselected").classed("patch_selected",true);
    d3.selectAll(".patch_unselected").classed("patch_unselected",false);

}


//invert selection
function invertselection()
{
    if(DEBUG) {console.log(d3.selectAll(".imgpatch_selected").size());}
    d3.selectAll(".imgpatch_selected").each(function(d){
        labelBorder =  "labelp_"+d[3];
        d3.select(this).classed("ui-selected",false);
        d3.select(this).classed(labelBorder,true);
        d3.select(this).classed("imgpatch_selected",false);
        d3.select(this).classed("imgpatch_unselected",true);
    })

    d3.selectAll(".patch_selected").classed("temp",true);
    d3.selectAll(".patch_unselected").classed("patch_selected",true);
    d3.selectAll(".patch_unselected").classed("ui-selected",true);
    d3.selectAll(".patch_unselected").classed("patch_unselected",false);

    d3.selectAll(".temp").classed("patch_unselected",true);
    d3.selectAll(".temp").classed("patch_selected",false);
    d3.selectAll(".temp").classed("ui-selected",false);
    d3.selectAll(".temp").classed("temp",false);

}


/* Sorting logic for Sorting by Predicted Color and GT color*/
function sortPred(){
    var $wrapper = $('.grid');

$wrapper.find('.patch').sort(function (a, b) {
    return +a.dataset.predname - +b.dataset.predname;
})
.appendTo( $wrapper );
}
function sortGT(){
    var $wrapper = $('.grid');

$wrapper.find('.patch').sort(function (a, b) {
    return +a.dataset.gtname - +b.dataset.gtname;
})
.appendTo( $wrapper );
}


function sortPredScore(){
    var $wrapper = $('.grid');

$wrapper.find('.patch').sort(function (a, b) {
    return +a.dataset.predscore - +b.dataset.predscore;
})
.appendTo( $wrapper );
}

function changelimit() {
        pageLimit = parseInt($( "#no_of_patch" ).val());
        $('#compact-pagination').pagination('updateItemsOnPage',pageLimit);
    };

/**
 * This function initializes the pagination ,
 * @param embedCnt -input parameter is the count of patches(embeddings)
 *                  obtained from api.patches_by_polygon.
 */
function initPagination(embedCnt){
    if(embedCnt>0) {
            showNextPatches(1,pageLimit);
            $('#compact-pagination').pagination({
                items: embedCnt,
                itemsOnPage: pageLimit,
                displayedPages:3,
                onPageClick: showNextPatches,
                cssStyle: 'compact-theme'
            });
        }
}

/**
 * This function for every next of previous page
 * @param pgno - loads the no of the page.
 */
function showNextPatches(pgno){
    var patches_by_page = new URL("{{url_for('api.patch_by_page',project_name=project.name)}}", window.location.origin);
        patches_by_page.searchParams.append("embeddingKey", searchKey);
        // pgno is actual page number on the grid , need to subtract one to get the correct page data.
        patches_by_page.searchParams.append("pageNo", pgno-1);
        patches_by_page.searchParams.append("pageLimit", pageLimit);
        fetch(patches_by_page).then(response => {
            return response.json();
        }).then((data) => {
                if(data){
                $('#filter_patch').val("All");
                // plotgrid(data.patch_data,data.patch_images);
                plotgrid(data.patch_data);
                // these are global variable
                // will be used to update the plot grid after ground truth label updates are done.
                gridData = data.patch_data;
                // patchImgData = data.patch_images;
                }
                else{
                    addNotification("Error: No Data for Patches.");
                }
            });
}

function updateCurrentPlot(ids,gt) {
    if (curr_plotted_jsonData != null) {
        embeddings = curr_plotted_jsonData.embedding;
        embeddings.forEach(function(element) {
            var elem_id = String(element[0]);
            if(ids.includes(elem_id)){

                element[3]=gt;
                element[4]=gt;
            }
        });
        curr_plotted_jsonData.embedding = embeddings;
        // loadData(curr_plotted_jsonData,false,'labelling');
    }
    // updateScatter(curr_plotted_jsonData,false,'labelling');
    initialize_plots(init_status=false,action_type='labelling');
}

function filterPatch()
{
    var filter_val =  $( "#filter_patch" ).val();

    if(filter_val == "UL"){
        filter_gridData = gridData.filter(function(d,i) { return d[3] == -1});
    }
    else if(filter_val == "L"){
        filter_gridData = gridData.filter(function(d,i) { return d[3] > -1});
    }else {
    filter_gridData = gridData;
    }
    // plotgrid(filter_gridData,patchImgData);
    plotgrid(filter_gridData);
}