var imageCount=0;
var DEBUG = false;
var proj_embed_iteration = -2;
var proj_make_patches_time = "None";

/**
 * Init function to be called to update the buttons and plots
 */
function init() {
    imageCount = "{{project.nImages}}";//getImageCount("{{ project.id }}");
    document.getElementById("no_of_images").innerHTML = imageCount;
    // console.log("{{project.embed_iteration}}");
    proj_embed_iteration = "{{project.embed_iteration}}";
    proj_make_patches_time = "{{project.make_patches_time}}";
    if(imageCount>0 && proj_make_patches_time != "None"){
        updateProjectStatistics();
    }
    updatePageDisplay();
    loadRunningTimers();
    //GeneratePlot if embedding done and also add the label classes and buttons and set them to disable=true.
    generatePlots(true);
}

/**
 * Checks for existing running jobs
 */
function loadRunningTimers() {
    const project_id = "{{ project.id }}";
    const completed_callback_function = updatePageDisplay;
    if(proj_make_patches_time == "None")
    {
        cmds_to_check = ["make_patches"];
        loadRunningJobsForProject(project_id, completed_callback_function,cmds_to_check);
    }else{
        loadRunningJobsForProject(project_id, completed_callback_function);
    }
}


/**
 * Updates the buttons based on the current status of the Project.
 */
function updatePageDisplay() {
    /* Train, Embed and SearchPatch Button*/
    updateButtons();
    updateDisplayMessage(imageCount);
}

/**
 * Enable/Disable Train, Embed and SearchPatch button based on project workflow
 */
function updateButtons(){
    if (proj_make_patches_time == "None")
    {
        toggleButton("trainDLButton",true,"Train Dl not ready for use");
        toggleButton("makeEmbedButton",true,"Make Embed not ready for use");
        toggleButton("searchRelatedPatch",true,"Search not ready for use");

    } else
    {
        toggleButton("trainDLButton",false,"Train Dl ready for use");
        toggleButton("makeEmbedButton",false,"Make Embed ready for use");
        toggleButton("searchRelatedPatch",true,"Search not ready for use");
    }
}


/**
 * Updates the display message based on the current Status of the project.
 * Depends on global param imageCount.
 */
function updateDisplayMessage(){
     if (imageCount > 0)
     {
           if(proj_make_patches_time == "None")
            {
                document.getElementById("message").style.display = "block";
                document.getElementById("dispMessage").innerText="Click on Images Button on top and Make Patches";
                document.getElementById("dispMessage").style.display = "block";
                document.getElementById("graphView").style.display = "none";
            }
            else if(proj_make_patches_time != "None" && proj_embed_iteration > -2)
            {
                document.getElementById("message").style.display = "none";
                document.getElementById("dispMessage").style.display = "none"
                document.getElementById("graphView").style.display = "block";


            }
            else{
                document.getElementById("message").style.display = "block";
                document.getElementById("dispMessage").innerText="For Graphs - Click on 1.Embed Patches or 2.Train DL and Embed Patches.";
                document.getElementById("dispMessage").style.display = "block";
                document.getElementById("graphView").style.display = "none";
            }
    } else {
            document.getElementById("message").style.display = "block";
            document.getElementById("dispMessage").style.display = "block"
            document.getElementById("graphView").style.display = "none";
    }
}

/**
 * Updates the Project Iteration post a Training
 */
function updateProjectIteration(){
    let table_name = 'project';
    let col_name = 'id';
    let operation = '==';
    let value = "{{ project.id }}";
    let project_iteration = getDatabaseQueryResults(table_name, col_name, operation, value).data.objects[0].iteration;
    if (project_iteration != null) {
        document.getElementById("iteration").innerHTML = project_iteration;
    }
    toggleButton("makeEmbedButton",false,"Make Embed ready for use");
}

/**
 * Enables(on false) or Disables(on true)
 * 1) radio buttons for color_by and filter_by and the dropdown of the ScatterPlot.
 * 2) ShowPatches checkbox
 * 3) Reset Button
 * 4) SearchPatches Button.
 * @param btnState
 */
function toggleScatterPlotButtons(btnState,caller)
{
    let status = "";
    $('input[name=color_by]').attr("disabled",btnState);
    $('input[name=filter_by]').attr("disabled",btnState);
     if (btnState){
         $("#filterlabel").prop('disabled', 'disabled');
         if(caller != "toggle_patch_view")
         {
            document.getElementById("viewpatches").checked=false;
         }
         status = "not ready";
     }else{
         $("#filterlabel").prop('disabled', false);
         status = "ready";
     }
    document.getElementById("viewpatches").disabled=btnState;
    document.getElementById("resetBtn").disabled = btnState;
    toggleButton("searchRelatedPatch",btnState,"Search is "+status+" for use");
     // console.log("called by "+caller + " set to ("+ btnState+")");
}

/** OnInit
 * Create class label drop down and Disable the GridPlot Buttons
 * Disables the ScatterPlot Buttons
 * Initializes the plots if Embed is already done.
 * @param disp_plot_buttons default is false(disable)
 */
function generatePlots(disp_plot_buttons = false){
    //loads the grid plot buttons and sets them to inactive
    loadGridPlotButtons(disp_plot_buttons);
    toggleScatterPlotButtons(disp_plot_buttons,"generatePlot");
    if(proj_embed_iteration > -2)
    {
        initialize_plots();
    }
}

/**
 * Invokes the Train DL component and trains the model.
 * */
function train_dl()
{
    addNotification("Training of DL Model #{{ project.iteration+1 }} starting.");
    addNotification("Note: 'Embed Patches' is unavailable during DL training.");
    toggleButton("makeEmbedButton",true,"Make Embed not ready for use");
    const run_url = new URL("{{ url_for('api.train_dl', project_name=project.name) }}", window.location.origin);
    radioButtonState = false;
    return loadObjectAndRetry(run_url, updateProjectIteration);
}


/**
 *  Invokes a function to create embeddings
 */

function make_embed() {
    addNotification("'Embed Patches' Pressed.")
    toggleButton("trainDLButton",true,"Train Dl not ready for use");
    let url = "{{  url_for('api.embed', project_name=project.name) }}";
    let run_url = new URL(url, window.location.origin)
    return loadObjectAndRetry(run_url, make_searchdb);
}

/**
 * Post embed make_searchdb is invoked to create the searchtree pkl file.
 */
function make_searchdb(){
    addNotification('Creating Data for Plot');
    toggleButton("trainDLButton",false,"Train Dl ready for use");
    let url = "{{  url_for('api.searchdb', project_name=project.name) }}";
    let run_url = new URL(url, window.location.origin);
    curr_xScale = null;
    curr_yScale = null;
    return loadObjectAndRetry(run_url, initialize_plots);
}


// zoom variables
const max_concurrency = 5
const max_redraw_points = 5000
let running_fetches = 0

function disable_embedding_plot() {
    waitCursor()

    // removes the html widget
    $(".lasso").remove() // will be added back on when draw_update_plot() is called after the points are fetched from the backend
    lasso = null

    // removes the event callbacks so it doesn't draw an invisible lasso that fetches while we're rendering
    // https://github.com/skokenes/D3-Lasso-Plugin/issues/3#issuecomment-184665536
    lasso_area.on("start", null);
    lasso_area.on("draw", null);
    lasso_area.on("end", null);
}
function enable_embedding_plot() {
    readyCursor();
}

/**
 *
 * @param response - obtained from the calling location
 * @param action -- obtained from the calling location (called from appendPoints or InitializePlot)
 */
async function updateScatter(response,status,action,fetch_id=0) {
    removeChartData();
    toggleScatterPlotButtons(true,"updateScatter for "+action);

    running_fetches--
    if (running_fetches == 0) {
        const updateStatus = loadData(response, status,action); // also adds lasso
        if(updateStatus) {
            addNotification("Plot is ready after " + action + "fetch "+ fetch_id);
            toggleScatterPlotButtons(false, "updateScatter post ("+action+")");
            enable_embedding_plot()
        }
    }
}

/**
 * Sets the ColorBy and SortBy Radio buttons to active.
 * Initializes the Scatter plot, makes a request to the server to fetch the data
 * in form of a json file and passes to the loadData() function
 *
**/
async function initialize_plots(init_status=true,action_type="load")
{
    if (!init_status) {
        disable_embedding_plot()
    }

    document.getElementById("message").style.display = "none";
    document.getElementById("dispMessage").style.display = "none";
    document.getElementById("graphView").style.display = "block";

    if(init_status)
    {
        addNotification("Initializing graph please wait.");
    }else {
        addNotification("Updating embedding graph after "+action_type +" please wait.");
    }
    /**
     *
     * @param yMin
     * @param yMax
     * @param xMin
     * @param xMax
     * @param plot_pts_by
     * @param filter_pts_by
     * @param class_pts_by
     * @param maxPoints
     * @param status
     * @param action **User action obtained in the initializePlot function**
     */
    function appendPoints(yMin, yMax, xMin, xMax,plot_pts_by,filter_pts_by,class_pts_by, maxPoints,status, action){
        
        let run_url = new URL("{{  url_for('api.view_embed', project_name=project.name) }}", window.location.origin);
        if(yMin == yMin) {
            run_url.searchParams.append("ymin", yMin)
            run_url.searchParams.append("ymax", yMax)
            run_url.searchParams.append("xmin", xMin)
            run_url.searchParams.append("xmax", xMax)
            run_url.searchParams.append("plot_by", plot_pts_by);
            run_url.searchParams.append("filter_by", filter_pts_by);
            run_url.searchParams.append("class_by", class_pts_by);
        }
        run_url.searchParams.append("maxpoints", maxPoints)

        if (running_fetches > max_concurrency) {
            console.warn('Already ' + max_concurrency + ' embedding calls in queue. Canceling this one.')
            return
        }
        const fetch_id = Math.round(Math.random() * 1e8)
        running_fetches++
        let init_time = performance.now();
        console.log("Intitating fetch for id: " + fetch_id +" @time: " +init_time );
        fetch(run_url, {
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => {
            let exit_time = performance.now();
            console.log("Complete fetch for id: " + fetch_id +" @time: " +exit_time );
            const json = response.json()
            if (!response.ok) {
                let error_message = 'ERROR ' + response.status + ': '
                if (json != null) {
                    error_message += json.error
                }
                else {
                    error_message += 'Unknown'
                }
                running_fetches--
                throw new Error(error_message);
            }
            return json
        })
        .then(parsed_response => {
            updateScatter(parsed_response,status,action,fetch_id)
        })
        .catch(error => {
            console.error('Error querying for embedding points: ', error);
            showWindowMessage(error);
        });
    }

    let yMin
    let yMax
    let xMin
    let xMax
    if(curr_xScale != null && curr_yScale != null) {
        yMin = curr_yScale.domain()[0]
        yMax = curr_yScale.domain()[1]
        xMin = curr_xScale.domain()[0]
        xMax = curr_xScale.domain()[1]
    }
    let plot_points_by = $("input[name='color_by']:checked").val();
    let filter_points_by = $("input[name='filter_by']:checked").val();
    let class_points_by = $("#filterlabel").val();

    appendPoints(yMin, yMax, xMin, xMax, plot_points_by,filter_points_by,
            class_points_by, max_redraw_points,init_status,action_type);
}

function removeChartData(){
    d3.select("svg").remove();
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



