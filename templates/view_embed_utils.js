var shortcutBool = true;
var cntLabelClass = 0;

/* Function to obtain the labels for the current project*/
function get_project_labels(){
    let table_name = 'labelnames';
    let col_name = 'projId';
    let operation = '==';
    let value = "{{ project.id }}";
    let labelData = getDatabaseQueryResults(table_name, col_name, operation, value).data.objects;
    cntLabelClass = labelData.length;
    return labelData;

}


function editLabels(){
    data = get_project_labels();
    loadShortCuts(false);
    var dialogDiv = $("#dialog-form")
    dialogDiv.empty();
    var form = $("<form/>").attr("id",'updateform');
        $("<input type='hidden' />")
        .attr("id", "Labelcnt")
        .attr("value",data.length)
        .appendTo(form);

    Object.entries(data).forEach(([k,v]) => {
    var div = $("<div/>")
              .attr("class","form-group");
        $("<label />")
            .attr("for","Label_id:"+v.label_id)
            .text("Label_id:"+v.label_id+"  ")
            .appendTo(div);
        $("<input type='text' />")
            .attr("id", "Label_id_"+v.label_id)
            .attr("name", "Label_id:"+v.label_id)
            .attr("value",v.label_name)
            .appendTo(div);
        $("<input type='hidden' />")
            .attr("id", "Label_row_id_"+v.label_id)
            .attr("value",v.id)
            .appendTo(div);
        form.append(div);
    })
    $("#dialog-form").append(form);

    dialog = $('#dialog-form').dialog({
        title: 'Update Label Names.',
        draggable: true,
        resizable: false,
        closeOnEscape: false,
        modal: true,
        autoOpen: false,
        buttons: {
            'Update' : {
                text : 'UpdateLabel',
                id : 'updateLabel',
                click : update_label_names
            } ,
            'Cancel' : {
                text : 'Cancel',
                id : 'canceUpdateLabel',
                click : function(){
                dialog.dialog('close');
                 loadShortCuts(true);
                    }
            }
        }
    });
    dialog.dialog("open");
}


/*function to load the label drop down options and the buttons for Labelling.*/
function loadGridPlotButtons(optionState=true) {
    labelData = get_project_labels();

    d3.select("#labelSelect").remove();
    d3.select("#applyLabelBtn").remove();
    d3.select("#updateLabelBtn").remove();
    d3.select("#selectAllBtn").remove();
    d3.select("#invertBtn").remove();
    d3.select("#filterlabel").selectAll("*").remove();

    //Dropdown for class labels for GridPlot.
    var label_options = d3.select("#labeldiv");
    var dropdownButton = label_options.append('select')
                                    .attr("id","labelSelect")
                                    .attr("class","label_0 text-right")
                                    .style("width","80px");

    dropdownButton.selectAll('myOptions')
                    .data(labelData)
                    .attr("id","patch_labels")
                    .enter().append('option')
                    .text(function (d) {return d.label_id+"-"+d.label_name;})
                    .attr("value",function (d) {return d.label_id; })
                    .attr("class",function (d) {return "label_"+ d.label_id;} )
                    .style("margin-left","2px")


    //Dropdown to filter by class on scatter plot
    var filterlabeldrpdown = d3.select("#filterlabel");
    //Manually adding a ALL option to the existing label data.
    var allObj = {id:0,label_color:"white",label_id:-1,label_name:"All"}
    var filterData = labelData;
    filterData.unshift(allObj);
    if(DEBUG) {console.table(filterData);}
    filterlabeldrpdown.selectAll('mylbl_options')
                    .data(filterData)
                    .attr("id","labelfilter")
                    .enter().append('option')
                    .text(function (d) {
                        if(d.label_id == -1){
                            return d.label_name;
                        }else{
                        return d.label_id+"-"+d.label_name;
                        }
                    })
                    .attr("value",function (d) {return d.label_id; })
                    .attr("class",function (d) {return "label_"+ d.label_id;} )
                    .style("margin-left","2px");



    //Adding the apply button to the grid plot
    label_options.append("button")
        .attr("id","applyLabelBtn")
        .attr("class","btn btn-secondary buttonDisp text-right")
        .style("margin-right","3px")
        .text("Apply Label")
        .on("click",updateGroundTruth);

    //Adding the Add LabelNames Button.
    label_options.append("button")
        .attr("id","updateLabelBtn")
        .attr("class","btn btn-secondary buttonDisp text-right")
        .style("margin-right","3px")
        .text("Add LabelNames")
        .on("click",editLabels);


    label_options.append("button")
        .attr("id","selectAllBtn")
        .attr("class","btn btn-secondary buttonDisp text-right")
        .style("margin-right","3px")
        .text("Select All")
        .on("click",selectall);

    label_options.append("button")
        .attr("id","invertBtn")
        .attr("class","btn btn-secondary buttonDisp text-right")
        .text("Invert")
        .on("click",invertselection);

  d3.select("#labelSelect").on("change", function(d) {
         // onchange="this.className=this.options[this.selectedIndex].className"
         // recover the option that has been chosen
         if( d3.select(this).attr("class") !=null){
             var classes = d3.select(this).attr("class").split(" ");
             for (i=0;i<classes.length;i++){
                 if(classes[i].startsWith("label_")) {
                     d3.select(this).classed(classes[i], false);
                 }
             }
        }
         var selectedOption = d3.select(this).property("value");
         let class_name = "label_"+selectedOption;
         d3.select(this).classed(class_name,true);
     });
    // Enable/Disable the options.
     setLabelOptions(optionState);
     // loadShortCuts(true,labelData.length);
     loadShortCuts(true);
}

function setLabelOptions(actionVal)
{
     document.getElementById("applyLabelBtn").disabled = actionVal;
     document.getElementById("updateLabelBtn").disabled = actionVal;
     if (actionVal){
         $("#labelSelect").prop('disabled', 'disabled');
     }else{
         $("#labelSelect").prop('disabled', false);
     }

     document.getElementById("labelSelect").disabled = actionVal;
     document.getElementById("selectAllBtn").disabled = actionVal;
     document.getElementById("invertBtn").disabled = actionVal;
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// key bindings:
function loadShortCuts(shortcutBool)
{
    if (shortcutBool) {
        shortcut.add("q", function () {
            let myInput = d3.select("input[name=color_by][value='1']");
            myInput.property("checked", true);
            myInput.on("change")();
        });
        shortcut.add("w", function () {
            let myInput = d3.select("input[name=color_by][value='2']");
            myInput.property("checked", true);
            myInput.on("change")();
        });
        shortcut.add("z", function () {
            let myInput = d3.select("input[name=filter_by][value='-1']");
            myInput.property("checked", true);
            myInput.on("change")();
        });
        shortcut.add("x", function () {
           let myInput = d3.select("input[name=filter_by][value='1']");
            myInput.property("checked", true);
            myInput.on("change")();
        });
        shortcut.add("c", function () {
            let myInput = d3.select("input[name=filter_by][value='0']");
            myInput.property("checked", true);
            myInput.on("change")();
        });
        shortcut.add("v", function () {
            let myInput = d3.select("input[name=filter_by][value='2']");
            myInput.property("checked", true);
            myInput.on("change")();
        });
        shortcut.add("b", function () {
            let myInput = d3.select("#filterlabel")
            myInput.property("value", '-1');
            myInput.on("change")();
       });
        shortcut.add("n", function () {
            let myInput = d3.select("#filterlabel")
            myInput.property("value", '0');
            myInput.on("change")();
        });
        shortcut.add("m", function () {
            let myInput = d3.select("#filterlabel")
            myInput.property("value", '1');
            myInput.on("change")();
        });
        for(lbl_shrtcut=0;lbl_shrtcut<cntLabelClass;lbl_shrtcut++)
        {
            let lbl_val = String(lbl_shrtcut);
            if($("#labelSelect option[value="+lbl_val+"]").val() != undefined)
            {
                shortcut.add(lbl_val, function () {
                    $("#labelSelect").val(lbl_val).attr('class', 'label_'+lbl_val);
                });
            }
        }
        shortcut.add("enter", function () {
            $("#applyLabelBtn").click();
        });
        shortcut.add("u", function () {
            $("#updateLabelBtn").click();
        });
        shortcut.add("a", function () {
            $("#selectAllBtn").click();
        });
        shortcut.add("s", function () {
            $("#invertBtn").click();
        });
        shortcut.add("r", function () {
            resetPlot();
        });
     }else{
        //Need to remove if a user is using these character for Update Label Names.
        shortcut.remove("q");
        shortcut.remove("w");
        shortcut.remove("z");
        shortcut.remove("x");
        shortcut.remove("c");
        shortcut.remove("v");
        shortcut.remove("b");
        shortcut.remove("n");
        shortcut.remove("m");
        shortcut.remove("u");
        shortcut.remove("a");
        shortcut.remove("s");
        shortcut.remove("r");
        for(lbl_shrtcut=0;lbl_shrtcut<cntLabelClass;lbl_shrtcut++)
        {
            let lbl_val = String(lbl_shrtcut);
            shortcut.remove(lbl_val);
        }
    }
}


/**
 * This function is used to show the percentage of embedding shown
 * @param totalres - total embedding points
 * @param providedres - no of embedding points shown in plot.
 */
function updateEmbeddingPercent(totalres,providedres){
    percentage = Math.round(providedres/totalres *100);
    if (isNaN(percentage)){percentage = 0;}
    document.getElementById('embed_info_dot').value = percentage;
    document.getElementById('maxpoints').innerHTML = percentage+"%";
}

function get_search_approach_options(){
    // paramList =["Embedding","Feature Vector"]
    paramList ={"Embedding":"embed","Feature Vector":"featvec"}
    return paramList;
}



function search_patch(){
    loadShortCuts(false);
     $("#myPform").trigger('reset');
     $("#imagePreview").attr('src','');
     $("#imagePreview").css("display", "none");
    approachValues = get_search_approach_options();
    $('#search_approach').empty();

    var select = $('<select>').prop('id', 'approach').prop('name', 'approach');
    Object.entries(approachValues).forEach(([k,v]) => {
        select.append($("<option>")
        .prop('value', v)
        .text(k.charAt(0).toUpperCase() + k.slice(1)));
        });
        var label = $("<label>").prop('for', 'approach')
                    .text("Choose an approach: ");
        var br = $("<br>");
    $('#search_approach').append(label).append(select).append(br);
    $('#searchPatch').modal('show');
}

function uploadSearchImage(project_name)
{
     validInput = validateSearchPatchesInput();
     if(validInput)
     {
         loadShortCuts(true);
            $('#searchPatch').modal('hide');
            const form = document.getElementById( "myPform" );
            let data = new FormData(form);
            let xhr = new XMLHttpRequest();
            let run_url = "{{ url_for('api.image_search', project_name='!!!!!') }}";
            run_url = run_url.replace(escape("!!!!!"),project_name);
            xhr.onreadystatechange = function ()
            {
                if (xhr.readyState == 1) {
                   addNotification("Please wait system is searching for patches.");
                   waitCursor();

                }
                else if(xhr.readyState == 2 && xhr.status == 400)
                {
                    showWindowMessage('ERROR 400 occured no patches found.');
                    readyCursor();

                }
                else if(xhr.readyState == 4 && xhr.status != 400)
                {
                    if (JSON.parse(xhr.response).embeddingCnt == 0) {
                        addNotification("No matching patches were found");
                        readyCursor();
                    }else{
                        addNotification("Loading matched patches.");
                        obtainFilteredPatchs(JSON.parse(xhr.response));
                    }
                }else if (xhr.readyState == 0){
                    alert("Error uploading files for project : '"+projectname+".")
                    readyCursor();
                }
            };
            xhr.open("POST", run_url, true);
            xhr.send(data);
        }
}

function validateSearchPatchesInput(){
    let no_of_objects =  parseInt(document.getElementById("no_of_objects").innerHTML);
    if($('#imagePreview').attr('src') == '')
    {
        alert('please select an image for upload');
        return false;
    }else if($('#max_threshold').val() =='' || isNaN($('#max_threshold').val()))
    {
        alert('Please enter a number for Maximum Threshold');
        return false;
    }else if ($('#nneighbors').val() =='' || isNaN($('#nneighbors').val()))
    {
        alert('Please enter a number for NNeighbors');
        return false;
    }else if ($('#nneighbors').val() >= no_of_objects)
    {
        alert('NNeighbors must be lesser than No of Objects in the project');
        return false;
    }else{
        return true;
    }
}

function obtainFilteredPatchs(jsonData){
    if (typeof jsonData === 'undefined') {
        alert('{{error_message}}');
        addNotification('{{error_message}}');
        throw new Error('{{error_message}}');
    }
    document.getElementById("selectPatchCnt").innerHTML = jsonData["embeddingCnt"] + " Patch-Retrieved"
    initGrid(jsonData["embeddingCnt"],jsonData["embeddingKey"]);

}

function waitCursor()
{
    document.getElementById("graphView").style.cursor = "wait";
}

function readyCursor(){
    document.getElementById("graphView").style.cursor = "auto";
}


function show_help(){
    window.open("{{ url_for('html.view_help')}}");
}