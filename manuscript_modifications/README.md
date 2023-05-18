### PatchSorter modifications for the detection of tumor buds in pulmonary squamous cell carcinoma use case


Modifications were made for use case 2 of the PatchSorter article to allow for the presentation of additional context.
For replicating the behaviour of the modified PatchSorter instance, copy the `view_patchgrid_plot.js` and `view_embed_plot.js` files into the `templates` folder of your PatchSorter instance.

Quick overview of the changes made using the diff syntax:

``` 
--- PatchSorter/templates/view_patchgrid_plot.js
+++ PatchSorter_usecase2/templates/view_patchgrid_plot.js
@@ -67 +67 @@
                 .attr("id",function(d, i) { return "patchid_"+d[0]})

        	         .attr("class",function(d, i) { return "labelp_"+d[3]})

                 .classed("imgpatch_unselected",true)


                 .attr("src",function(d, i) {


-                        let patch_url = "{{ url_for('api.patch_image', project_name=project.name, patch_id='!!!!!') }}"

-                        patch_url = patch_url.replace(escape("!!!!!"),d[0]);



+                        let patch_url = "{{ url_for('api.patch_image', project_name=project.name, patch_id='!!!!!') }}"

+                        patch_url = patch_url

+                                        .replace(escape("!!!!!"),d[0])

+                                        .replace('image', 'context')


                         return patch_url;

                         // return getImage(d[0])

                 })

@@ -121 +131 @@

 var showContextMenu = function(d) {

     let patch_id = d[0];


-     let context_url = "{{ url_for('api.patch_context_image', project_name = project.name, patch_id= '!!!!!') }}";

+     let context_url = "{{ url_for('api.patch_image', project_name = project.name, patch_id= '!!!!!') }}";

     context_url = context_url.replace(escape("!!!!!"), patch_id);

     let context_patch_name = "context_"+patch_id;

     if (d3.event.pageX || d3.event.pageY) {
```

``` 
--- PatchSorter/templates/view_embed_plot.js
+++ PatchSorter_usecase2/templates/view_embed_plot.js
@@ -595 +595 @@
             .attr("y", function () {

                 return curr_yScale(y_cord);

             })

-            .attr("width", 35)

-            .attr("height", 35)

+            .attr("width", 70)

+            .attr("height", 70)

             .classed("anim_img",true);

 }


``` 

