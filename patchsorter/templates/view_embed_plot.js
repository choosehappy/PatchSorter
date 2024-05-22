var curr_xScale= null;
var curr_yScale = null;
var preImgSize = 100; //Used by mouse hover.
var curr_plotted_jsonData = null;
//Constants defined for Filtering.
const Plot_P = 1;
const Plot_GT = 2;
const Filter_UL = 0;
const ALL = -1

/*Variables defined for SVG */
svg_width = 700;
svg_height = 500;
/* width and height represent the plot area and will be used to define the lasso area.*/
/* Margins to use for plot */
var margin = {top: 20, right: 20, bottom: 30, left: 40},
width = svg_width - margin.left - margin.right,
height = svg_height - margin.top - margin.bottom;

/* patch_svg holds the plot elements and scatter_plt_svg holds the patch_svg element. */
var patch_svg, scatter_plt_svg;
/* Used to show the color codes on sortby color */
var color_map = ["rgb(228,26,28)",'rgb(55,126,184)','rgb(77,175,74)','rgb(152,78,163)','rgb(255,127,0)','rgb(255,255,51)','rgb(166,86,40)','rgb(247,129,191)','rgb(153,153,153)'];
/* Radius of the plotted circles. Color for Unlabelled */
var radius = 3.5;
var non_predict = "white";

/* Variable defined to handle mouseover delay */
var hovertimer= null;
/* Variable defined to capture the lasso and drawn lasso path */
var lasso_path="";
var lasso = null;
var lasso_area;
//Variables defined for Zoom functions
var zoomfactor = 1;

var hoverImgSize = 100;
var minZoom = false;
// Plot elements
var circles=null;
var gY = null;
var gX = null;
var curr_action = null;
//Used to check for infinite zoom-out.
var initial_xMin
var initial_xMax
var initial_yMin
var initial_yMax

/*
This function helps load the data in form of a Scatter Plot.
 */
function loadData(jsonData,init_status,action) {

    plot_status = false;
    /* check if data was obtained */
    if (typeof jsonData === 'undefined') {
        alert('{{error_message}}');
        addNotification('{{error_message}}');
        throw new Error('{{error_message}}');
    }
    else
    {
        /* Remove any previous plot element */
        d3.select("#scatterContainter").selectAll("*").remove();
        /* Set dimensions for svg based on the viewBox */
        scatter_plt_svg = d3.select("#scatterContainter")
            .append("svg")
            .attr("id", "scatterplt_svg")
            .attr("preserveAspectRatio", "xMinYMin meet")
            .attr("viewBox", [0, 0, svg_width, svg_height])
            .classed("svg-content", true);
        /* Retrieve filter elements to filter data */
        var init_plotby = $("input[name='color_by']:checked").val();
        var init_filterby = $("input[name='filter_by']:checked").val();

        if(init_filterby == Filter_UL && init_plotby == Plot_GT){
            /* Reset and Disable set toggle to true */
            resetFilterLabel(true);
         }
        var init_classby = $("#filterlabel").val();


        /* Retrieving the embedding data to plot from json */
        var orig_plot_data = jsonData["embedding"]
        curr_plotted_jsonData = jsonData;
        curr_action = action;
        /* if True - this is the initial plot and initialize the curr_xScale and curr_yScale. */
        if (init_status) {

            curr_xScale = d3.scaleLinear().domain([jsonData["xmin"], jsonData["xmax"]]).range([0, width]);
            curr_yScale = d3.scaleLinear().domain([jsonData["ymin"], jsonData["ymax"]]).range([height, 0]);

            initial_yMin = curr_yScale.domain()[0]
            initial_yMax = curr_yScale.domain()[1]
            initial_xMin = curr_xScale.domain()[0]
            initial_xMax = curr_xScale.domain()[1]
        }

        plot_status = draw_update_plot(orig_plot_data, init_filterby, init_plotby, init_classby, curr_xScale, curr_yScale,action);
        /**
         * Capturing Onchange Color By - Predict vs Groundtruth
         */
        d3.selectAll(("input[name='color_by']")).on("change", function () {
            let plotby = $("input[name='color_by']:checked").val();
            let filterby = $("input[name='filter_by']:checked").val();
            let classby = $("#filterlabel").val();
            d3.select("#patch_svg_group").remove();
            //re-initialize the plots for Serverside filtering.
            initialize_plots(init_status=false,action_type='data_filter');
        });
        /**
         * Capturing onChange of Filter By - All vs Labelled vs UnLabelled vs Discordant
         */
        d3.selectAll(("input[name='filter_by']")).on("change", function() {
            let plotby = $("input[name='color_by']:checked").val()
            let filterby = $("input[name='filter_by']:checked").val()
            let classby = $( "#filterlabel" ).val();
            d3.select("#patch_svg_group").remove();
            //re-initialize the plots for Serverside filtering.
            initialize_plots(init_status=false,action_type='data_filter');
        });

        /**
         * Capturing onChange of filterClass label - ALL, label0, label1 etc
         */
       d3.select("#filterlabel").on("change", function() {
            //Remove the class of earlier option and add new class to change the color in the dropdown
            var classes = d3.select("#filterlabel").attr("class").split(" ");
            if(classes !=null){
                for (i=0;i<classes.length;i++){
                    if(classes[i].startsWith("label_")) {
                        d3.select("#filterlabel").classed(classes[i], false);
                    }
                }
            }
            var selectedOption = d3.select("#filterlabel").property("value");
            let class_name = "label_"+selectedOption;
            d3.select("#filterlabel").classed(class_name,true);
           //Filter the plot data
            let plotby = $("input[name='color_by']:checked").val()
            let filterby = $("input[name='filter_by']:checked").val()
            let classby = $( "#filterlabel" ).val();
            d3.select("#patch_svg_group").remove();
            //re-initialize the plots for Serverside filtering.
           initialize_plots(init_status=false,action_type='datafilter');

        });
        if(plot_status)
        {
            updateEmbeddingPercent(jsonData["totalres"], jsonData["providedres"]);
        }
    }
    return plot_status;
}



var zoomed_count = 0


// at regular intervals, check if a redraw is needed, but don't redraw while zooming
var last_redraw_time = 0
var last_zoom_time = 1
var last_checked_time = 1
const interval_seconds = 0.3
window.setInterval(
    function(){
        const needs_redraw = last_redraw_time < last_zoom_time &&
                                                last_zoom_time < last_checked_time
        if (proj_embed_iteration > -2 && needs_redraw)
        {
            if(curr_action == "zoom"){
                current_xMin = curr_xScale.domain()[0]
                current_xMax = curr_xScale.domain()[1]
                current_yMin = curr_yScale.domain()[0]
                current_yMax = curr_yScale.domain()[1]

                if (current_xMin < initial_xMin ||
                    current_xMax > initial_xMax ||
                    current_yMin < initial_yMin ||
                    current_yMax > initial_yMax) {

                    //Disallow infinite zoom-out from initial zoom level
                } else {
                    initialize_plots(init_status=false,action_type=curr_action)
                }
            }
            last_redraw_time = Date.now()
        }
        last_checked_time = Date.now()
    },
    interval_seconds * 1000
);

/* Function to draw all plots every time a change is made or on initialization of the page*/
function draw_update_plot(plotdata, filterby, plotby, classby,xScl, yScl,action) {
    // console.time("Draw_Scatter_Plot");
    // console.time("DrawSVG");
    //Add an initial SVG
    scatter_plt_svg.selectAll("*").remove(); //To fix the multiple lasso issue.
    patch_svg = scatter_plt_svg.append("g")
        .attr("class", "patch_svg_group")
        .attr("id", "patch_svg_group")
        .attr("transform", "translate(" + margin.left + "," + margin.top + ")");

    // create a clipping region
    patch_svg.append("defs").append("clipPath")
        .attr("id", "clip")
        .append("rect")
        .attr("width", width)
        .attr("height", height)

    //Add x and y axis to the graphs
    const xAxis = d3.axisBottom(xScl).ticks(10);
    const yAxis = d3.axisLeft(yScl).ticks(10);

    //Define the Lasso Area for the graphs
    lasso_area = patch_svg.append("rect")
        .attr("id", "lasso_area")
        .attr("width", width)
        .attr("height", height)
        .style("opacity", 0)

    // Adds Y-Axis as a 'g' element
    gY = patch_svg.append("g")
                        .attr("class", "yaxis").call(yAxis);
    // AddsX-Axis as a 'g' element
    gX = patch_svg.append("g").attr("class", "xaxis")
        .attr('transform', 'translate(0,' + (height) + ')')
        .call(xAxis);

    patch_svg.append("text")
        .attr("transform",
            "translate(" + (width / 2) + " ," +
            (height + margin.bottom) + ")")
        .style("text-anchor", "middle")
        .style("font-size", "x-small")
        .text("Zoom with Mouse Wheel and Pan on X/Y axis");

    // Draw Datapoints
    var points_g = patch_svg.append("g")
        .attr("clip-path", "url(#clip)")
        .classed("points_g", true);
    // console.timeEnd("DrawSVG");
    // console.time("PlotPoints");
    circles = points_g.selectAll("circle")
        .data(plotdata)
        .enter()
        .append("circle")
        .attr('id',d => { return "dot_"+d[0]})
        .attr('cx', function (d, i) {
            return xScl(d[1]);
        })
        .attr('cy', function (d, i) {
            return yScl(d[2]);
        })
        .attr('fill', function (d, i) {
            if (plotby == 1) {
                //Color is based on the predictions
                if (typeof color_map[d[4]] != 'undefined') {
                        return color_map[d[4]];
                } else {
                        return non_predict;
                }
            } else {
                //Color is based on the ground truth
                if (typeof color_map[d[3]] != 'undefined') {
                        return color_map[d[3]];
                } else {
                        return non_predict;
                }
            }
        })
        .attr('r', radius)
        .attr("class", function(){
                                    if(plotby== 1){
                                        return 'circlePredict'
                                    }else{
                                        return 'circleNonpredict'
                                    }
                                   })
        .on("mouseover", delayhandleMouseOver)
        .on("mouseout", handleMouseOut); //Commented out temporarily till testing complete
    // console.timeEnd("PlotPoints");
    // console.time("AddLasso");
    // Define the lasso
    lasso = d3.lasso()
        .closePathDistance(75) // max distance for the lasso loop to be closed
        .closePathSelect(true) // can items be selected by closing the path?
        .items(circles)
        .targetArea(lasso_area) // area where the lasso can be started
        .on("start", lasso_start) // lasso start function
        .on("draw", lasso_draw) // lasso draw function
        .on("end", lasso_end); // lasso end function

    patch_svg.call(lasso);
    // console.timeEnd("AddLasso");
    // console.time("AddZoom");
    // Pan and zoom
    const min_zoom = 0.5
    const max_zoom = 1e6
    const min_x = 0
    const min_y = 0
    var zoom = d3.zoom()
        .scaleExtent([min_zoom, max_zoom])
        .extent([[min_x, min_y], [width, height]])
        .on("zoom", zoomed);

    scatter_plt_svg.call(zoom).on("wheel.zoom", wheeled);//Enabling zoom on plot load.


    function wheeled(){
        const event = d3.event;
        const zoomDelta = 1.5
        const scale_factor = event.wheelDelta > 0 ? zoomDelta : 1.0/zoomDelta
        zoom.scaleBy(scatter_plt_svg.transition().duration(100), (scale_factor));
    }

    /**
     * Function to define a zoom
     */
    function zoomed()
    {
        const transform = d3.event.transform
        removeExistingLasso();
        gridpatchviewremove(); //will remove patches of the plot if show patches was used
        // document.getElementById("viewpatches").checked=false;
        // toggleScatterPlotButtons(true,"zoomed()");
        last_zoom_time = Date.now()
        curr_action = "zoom";
        const zoom_factor = transform.k
        var zoom_scale = parseInt(zoom_factor.toFixed(2));
        zoom_scale = zoom_factor
        var new_xScale= null;
        var new_yScale = null;
        new_xScale = transform.rescaleX(xScl);
        new_yScale = transform.rescaleY(yScl);
        curr_xScale = new_xScale;
        curr_yScale = new_yScale;
        redrawCircles(plotdata);
    }
    // console.timeEnd("AddZoom");
    // console.timeEnd("Draw_Scatter_Plot");
    return true;
}

function redrawCircles(data){
    // console.time("Redraw_ON_ZOOM");
    gX.call(d3.axisBottom(curr_xScale).ticks(10));
    gY.call(d3.axisLeft(curr_yScale).ticks(10));
    circles.data(data)
        .attr('cx', function (d, i) {
            return curr_xScale(d[1])
        })
        .attr('cy', function (d, i) {
            return curr_yScale(d[2])
        });
    // console.timeEnd("Redraw_ON_ZOOM");
}

function resetPlot()
{
    /* Reseting the scales */
    curr_xScale = null;
    curr_yScale = null;
    /* Reset all the filter options on Scatter Plot to defaults */
    $("input[name='color_by']").val([1]);
    $("input[name='filter_by']").val([-1]);
    /* Reset and keep it enabled set toggle to false */
    resetFilterLabel(false);
    curr_action = "reset";
    waitCursor();
    initialize_plots(init_status=true,action_type=curr_action);
}

/**
 * Resets the labeldrop down on ScatterPlot to ALL
 * and sets the background to white color
 */
function resetFilterLabel(toggle=true){
    $("#filterlabel").removeClass("label_"+$("#filterlabel").val())
    $("#filterlabel").val($("#filterlabel option:first")).addClass("label_-1");
    $("#filterlabel").val($("#filterlabel option:first").val());
    if(toggle){
        $("#filterlabel").prop('disabled', 'disabled');
    }else{
        $("#filterlabel").prop('disabled', false);
    }
}


//Lasso Functions
var lasso_start = function () {
        lasso.items()
            .classed("not_possible", true)
            .classed("selected", false);
    };

var lasso_draw = function () {
        gridpatchviewremove();
        document.getElementById("viewpatches").checked=false;
        lasso.possibleItems()
            .classed("not_possible", false)
            .classed("possible", true)
        lasso.notPossibleItems()
            .classed("not_possible", true)
            .classed("possible", false);
    };

var lasso_end = function () {
        lasso.items()
            .classed("not_possible", false)
            .classed("possible", false);
        var selected = lasso.selectedItems()
            .classed("selected", true)
        var patch_selected = selected.data().map(d => d);
        if(lasso_path != "") {
             waitCursor();
            /* Retrieve filter elements to filter data */
            let plot_by = $("input[name='color_by']:checked").val();
            let filter_by = $("input[name='filter_by']:checked").val();
            let class_by = $("#filterlabel").val();
            var patches_by_polygon_url = new URL("{{url_for('api.patches_by_polygon',project_name=project.name)}}", window.location.origin);
            patches_by_polygon_url.searchParams.append("polystring", lasso_path);
            patches_by_polygon_url.searchParams.append("plot_by", plot_by);
            patches_by_polygon_url.searchParams.append("filter_by", filter_by);
            patches_by_polygon_url.searchParams.append("class_by", class_by);
            fetch(patches_by_polygon_url).then(response => {
                return response.json();
            }).then((data) => {
                if (data.embeddingCnt > 0) {
                    document.getElementById("selectPatchCnt").innerHTML = data.embeddingCnt + " Patch-Selected"
                    initGrid(data.embeddingCnt, data.embeddingKey);
                }
                else {
                    addNotification(data.message);
                    d3.select("#grid").remove();
                    document.getElementById("selectPatchCnt").innerHTML = "0 Patch-Selected";
                    readyCursor();
                }
            });
        }
    };

// Create Event Handlers for mouse
/*Obtains the patch image from server and displays it on the svg scatter graph on hover of mouse on a data point*/

function delayhandleMouseOver(d,i)
{
    clearTimeout(hovertimer);
    hovertimer = window.setTimeout(handleMouseOver.bind(this), 500, d, i);
}


function handleMouseOver(d,i)
{
    d3.select(this).attr({r: radius * 2});
    //Do not need a seperate variable but made for ease of understanding.
    let patch_id = d[0];
    let patch_url = "{{ url_for('api.patch_image', project_name=project.name, patch_id='!!!!!') }}"
    patch_url = patch_url.replace(escape("!!!!!"),patch_id);
    let patch_name = "patch_"+patch_id;
    patch_svg.append("image")
        .attr("id", "img_" + parseInt(d[1]) + "_" + parseInt(d[2])+ "_" + d[0])
        .attr("xlink:href", new URL(patch_url, window.location.origin))
        .attr("x", function () {
            return curr_xScale(d[1]) + 20;
        })
        .attr("y", function () {
            return curr_yScale(d[2]) + 10;
        })
        .attr("width", preImgSize)
        .attr("height", preImgSize);
    // Specify where to put label of text
    // Create an id for text so we can select it later for removing on mouseout
    patch_svg.append("text")
        .attr("id","t" + parseInt(d[1]) + "_" + parseInt(d[2]) + "_" + d[0])
        .attr("x",function () {
                return curr_xScale(d[1]) + 20;
            })
        .attr("y",function () {
                return curr_yScale(d[2]);
            })
        .text(patch_name) // Value of the text
        .style("font-size", "12px");
}

/*Removes the patch image from svg scatter graph on mouse out*/
function handleMouseOut(d, i)
{
    clearTimeout(hovertimer);
    // Use D3 to select element, change color back to normal
    d3.select(this).attr({r: radius});
    // Select image by id and then remove
    d3.select("#img_" + parseInt(d[1]) + "_" + parseInt(d[2])+ "_" + d[0]).remove(); // Remove the image
    // Select text by id and then remove
    d3.select("#t" + parseInt(d[1]) + "_" + parseInt(d[2])+ "_" + d[0]).remove();  // Remove text location
}

function toggle_patch_view_btn(obj)
{
    if($(obj).is(":checked")) {
        toggle_patch_view(true);
    }else {
        toggle_patch_view(false);
    }
}

function toggle_patch_view(display)
{
    if (display == true) {
        removeExistingLasso();
        addNotification("Retrieving Patches Initiated.");
        waitCursor();
        toggleScatterPlotButtons(true,"toggle_patch_view");
        var ids_url = new URL("{{ url_for('api.points_on_grid', project_name=project.name) }}", window.location.origin);
        ids_url.searchParams.append("ymin", curr_yScale.domain()[0]);
        ids_url.searchParams.append("ymax", curr_yScale.domain()[1]);
        ids_url.searchParams.append("xmin", curr_xScale.domain()[0]);
        ids_url.searchParams.append("xmax", curr_xScale.domain()[1]);
        ids_url.searchParams.append("plot_by", $("input[name='color_by']:checked").val());
        ids_url.searchParams.append("filter_by", $("input[name='filter_by']:checked").val());
        ids_url.searchParams.append("class_by", $("#filterlabel").val());

        fetch(ids_url).then(response => {
            return response.json();
        }).then((data) => {
            if(data.anim_patchids && data.anim_patchids.length > 0) {
                addNotification("Loading Patches please wait.");
                data.anim_patchids.forEach(gridpatchviewadd);
                addNotification("View Patches Ready.");
                readyCursor();
                toggleScatterPlotButtons(false,"toggle_patch_view_resp");

            }
            else{
                addNotification(data.error);
                readyCursor();
            }
        });
    }else{
        gridpatchviewremove();
        document.getElementById("viewpatches").checked=false;
    }
}

function gridpatchviewadd(patch_data)
{
    // Directly adding the image on the plot not checking for a specific point.
    // patch_dot = document.getElementById("dot_"+ patch_id);
        patch_id = patch_data[0];
        x_cord = patch_data[1];
        y_cord = patch_data[2];
        let patch_url = "{{ url_for('api.patch_image', project_name=project.name, patch_id='!!!!!') }}"
        patch_url = patch_url.replace(escape("!!!!!"), patch_id);
        patch_svg.append("image")
            .attr("id", "img_" + patch_id)
            .attr("xlink:href", new URL(patch_url, window.location.origin))
            .attr("x", function () {
                return curr_xScale(x_cord);
            })
            .attr("y", function () {
                return curr_yScale(y_cord);
            })
            .attr("width", 35)
            .attr("height", 35)
            .classed("anim_img",true);
}

function gridpatchviewremove() {
     d3.selectAll(".anim_img").remove();
}

/**
 * Function to remove lasso on zoom
 */
function removeExistingLasso(){
    let myobj = $(".lasso")
    myobj.remove();
    lasso_path = "";
    patch_svg.call(lasso);
}

/**
 * Funtion used to filter the embedding plot data based on value
 * @param filterby_val ( can be UL, L or D)
 * @param plot_data
 * @returns {filtered plotdata}
 */
/* Not Used as filtering is moved to serverside */
/*
function filter_by(filterby_val,plot_data)
{
    var filter_celldata = null;
    if(filterby_val == 0){
        filter_celldata = plot_data.filter(function(d,i) { return d[3] == -1});
    }
    else if(filterby_val == 1){
        filter_celldata = plot_data.filter(function(d,i) { return d[3] != -1});
    }
    else if(filterby_val == 2){
        filter_celldata = plot_data.filter(function(d,i) { return d[3]!=d[4] && d[3] != -1});
    }
    else{
        filter_celldata = plot_data;
    }
    return filter_celldata;
}*/
/* Removed from drawPlot*/
    // document.getElementById("viewpatches").checked=false;
    //Disabling client Side filtering and re-initialize the plots.
    /*
    if(filterby == 0 || filterby == 1 || filterby == 2 )
    {
        plotdata = filter_by(filterby,plotdata);
    }
    if (plotby == 1 && classby != -1) {
        plotdata = plotdata.filter(function (d, i) {
            return d[4] == parseInt(classby);
        });
    }
    if (plotby == 2 && classby != -1) {
        plotdata = plotdata.filter(function (d, i) {
            return d[3] == parseInt(classby);
        });
    }
    alert("New length of data "+plotdata.length);
    */