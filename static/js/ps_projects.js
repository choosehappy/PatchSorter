var DEBUG = false;
function insertTableRow(project) {
    // The project here is the response data in Json format
    let table = document.getElementById("projects-table").getElementsByTagName('tbody')[0];
    let rowIndex = table.rows.length;
    let row = table.insertRow(rowIndex);
    row.id = "projectRow_"+project.id;
    row.className="centerAlign";
    row.insertCell(0).innerHTML = "<button onclick=\"deleteProject('" + project.id + "','" + project.name + "')\">Delete</button>";
    row.insertCell(1).innerHTML = "<button onclick=\"editProject('" + project.id +"','"+ project.name+"','"+ project.description +"')\">Edit</button>" + addEditModal();
    row.insertCell(2).innerHTML = "<a href=\'" + project.name + "\\images\'>" + project.name + "</a>";
    var cellDesc = row.insertCell(3);
    cellDesc.innerHTML = project.description;
    cellDesc.id = "cell_"+project.id+"_projdesc";
    row.insertCell(4).innerHTML = project.date.replace("T", " ");
    row.insertCell(5).innerHTML = project.images.length.toString();
    row.insertCell(6).innerHTML = project.iteration;
    row.insertCell(7).innerHTML = project.no_of_label_type
    // The nubmer of labelled objects are 0 for a new project, will be update post make_patches
    row.insertCell(8).innerHTML = 0;
    // The nubmer of user labelled objects are 0 for a new project
    row.insertCell(9).innerHTML = 0;
    // The percent of labelled objects are 0 for a new project
    row.insertCell(10).innerHTML = 0;
}

function updateTableRow(project) {
    // The project here is the response data in Json format
    let rowObj = "projectRow_"+project.id;
    let cell_name = "cell_"+project.id+"_projdesc";
    // document.getElementById(rowObj).getElementsByTagName('td')[3].innerText = project.description;
    document.getElementById(cell_name).innerText = project.description;
    if(DEBUG){ console.log("New Desc " + document.getElementById(cell_name).innerText );}
    //Doing this to refresh the projects object on the index.html so that it has the correct description.
    location.reload();
}

var projectModule = angular.module("myApp", []);
projectModule.controller("myCtrl", function($scope, $http) {
    
    $scope.addProject = function() {
        this.myForm.$setPristine();
        this.myForm.$setUntouched();
        let data = $scope.formData;
        //Removed the date from here and added a default server date which will be entered automatically.
        // let time = new Date();
        // data["date"] = time.toISOString().substring(0, 19).replace("T", " ");
        $http.post("/api/db/project", data)
            .then(function (response) {
                //Changing this temporarily to load the data as it is creating some issues.
                // insertTableRow(response.data)
                location.reload();
                resetForm();
            }).catch(function (response) {
            alert('Error when trying to add project: ' + response.data.message);
        });
    };
    $scope.cancelAdd = function() {
        resetForm();
    }

    $scope.saveProject = function() {
        this.myEditForm.$setPristine();
        this.myEditForm.$setUntouched();
        let data = $scope.formData;
        let name = $('#edit_project_name').val();
        let projId = $('#edit_project_id').val();
        data['name'] = name;

        let run_url = "/api/db/project/" + projId;
        $http.put(run_url, data)
            .then(function (response) {
                updateTableRow(response.data)
                resetForm();
            }).catch(function (response) {
            alert('Error when trying to edit project: ');
        });
    };
    $scope.cancelEdit = function() {
        resetForm();
    }


    // Nested function that reset the form data
    function resetForm() {
        try{
            $scope.formData.name = "";
            $scope.formData.description = "";
            $scope.formData.no_of_label_type = "";
        } catch (e) {
        }
    }




}); // angular controller


// ask for confirmation and delete the images and/or project
function deleteProject(projectid, projectName) {
    let xhr = new XMLHttpRequest();
    let $dialog = $('<div></div>').html('SplitText').dialog({
        dialogClass: "no-close",
        title: "Delete Project",
        width: 400,
        height: 200,
        modal: true,
        // We have three options here
        buttons: {
            "Delete Project": function () {
                showLoadingWheel();
                let run_url = "api/db/project/" + projectid;
                $dialog.dialog('close');
                xhr.onreadystatechange = function () {
                    $dialog.dialog('close');
                    if (xhr.readyState == 4) {
                        let table = document.getElementById("projects-table").getElementsByTagName('tbody')[0];
                        let rowIndex =document.querySelector("#projectRow_"+projectid).rowIndex - 1;
                        if (rowIndex >= 0 && rowIndex < table.rows.length) {
                            document.getElementById("projects-table").getElementsByTagName('tbody')[0].deleteRow(rowIndex)
                        } else {
                            alert("Error when trying to delete project: '"+projectName+"'!")
                        }
                        hideLoadingWheel();
                    }
                };
                xhr.open("DELETE", run_url, true);
                xhr.send();
            },
            // Simply close the dialog and return to original page
            "Cancel": function () {
                $dialog.dialog('close');
            }
        }
    });
    $dialog.html("Do you want to delete the project: '"+projectName+"'?")
} // deleteProject


function editProject(projectid, projectName,projectDescription) {
    // console.log(projectid);
    $('#edit_project_id').val(projectid);
    $('#edit_project_name').val(projectName);
    $('#edit_project_desc').val(projectDescription);

    $('#editProj').modal();
} // deleteProject


function init() {
    hideLoadingWheel();
    let formBodyInput = document.getElementById("formBody");
    formBodyInput.addEventListener("keyup", function (event) {
        if (event.keyCode === 13) {
            event.preventDefault();
            document.getElementById("addProjectButton").click();
        }
    });
    $('#addNewProj').on('shown.bs.modal', function() {

        $("#project_name_input").val("");
        $("#project_name_input").focus();
        $("#project_description").val("");
        $("#no_of_label_type").val(2);
    });
}

function addEditModal(){
    let modalWindow = "<div id=\"editProj\" class=\"modal fade\">\n" +
        "            <div class=\"modal-dialog\">\n" +
        "                <div class=\"modal-content\">\n" +
        "                    <form name=\"myEditForm\">\n" +
        "                        <div class=\"modal-header\">\n" +
        "                            <button type=\"button\" class=\"close\" data-dismiss=\"modal\"><span\n" +
        "                                    aria-hidden=\"true\">&times;</span><span class=\"sr-only\">Close</span>\n" +
        "                            </button>\n" +
        "                            <h3 class=\"modal-title\">Edit project</h3>\n" +
        "                        </div>\n" +
        "                        <div class=\"modal-body\" id=\"formEditBody\">\n" +
        "                            <input type=\"hidden\" id=\"edit_project_id\"/>\n" +
        "                            <div class=\"form-group\">\n" +
        "                                <label for=\"recipient-name\" class=\"control-label\" >Project Name</label>\n" +
        "                                <input type=\"text\" class=\"form-control\" id=\"edit_project_name\" name=\"name\" ng-model=\"formData.name\" readonly>\n" +
        "                            </div>\n" +
        "                            <div class=\"form-group\">\n" +
        "                                <label for=\"message-text\" class=\"control-label\">Description</label>\n" +
        "                                <textarea type=\"text\" class=\"form-control\" id=\"edit_project_desc\" name=\"description\"\n" +
        "                                          ng-model=\"formData.description\" autocomplete=\"off\"></textarea>\n" +
        "                            </div>\n" +
        "                        </div>\n" +
        "                        <div class=\"modal-footer\">\n" +
        "                            <button type=\"button\" id= \"editProjectButton\" ng-click=\"saveProject()\" class=\"btn btn-primary\" data-dismiss=\"modal\">\n" +
        "                                Save\n" +
        "                            </button>\n" +
        "\n" +
        "                            <button type=\"button\" ng-click=\"cancelEdit()\" class=\"btn btn-default\" data-dismiss=\"modal\">Cancel</button>\n" +
        "                        </div>\n" +
        "                    </form>\n" +
        "                </div>\n" +
        "            </div>\n" +
        "        </div>\n"

    return modalWindow;
}


function showLoadingWheel(){
    $("#loader").show();
}
function hideLoadingWheel(){
    $("#loader").hide();
}