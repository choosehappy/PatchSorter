export type ClientOptions = {
    baseUrl: 'http://localhost:8000' | (string & {});
};
/**
 * ConfusionMatrixResponse
 */
export type ConfusionMatrixResponse = {
    /**
     * Gt Labels
     */
    gt_labels: Array<number>;
    /**
     * Pred Labels
     */
    pred_labels: Array<number>;
    /**
     * Matrix
     */
    matrix: Array<Array<number>>;
};
/**
 * HTTPValidationError
 */
export type HttpValidationError = {
    /**
     * Detail
     */
    detail?: Array<ValidationError>;
};
/**
 * LabelAssignByPolygonRequest
 */
export type LabelAssignByPolygonRequest = {
    /**
     * Polygon
     */
    polygon: {
        [key: string]: unknown;
    };
};
/**
 * LabelAssignResponse
 */
export type LabelAssignResponse = {
    /**
     * Updated
     */
    updated: number;
};
/**
 * LabelClassResponse
 */
export type LabelClassResponse = {
    /**
     * Label Class Id
     */
    label_class_id: number;
    /**
     * Project Id
     */
    project_id: number | null;
    /**
     * Name
     */
    name: string;
    /**
     * Color Code
     */
    color_code?: string | null;
    /**
     * Event Ts
     */
    event_ts: string;
};
/**
 * PatchResponse
 */
export type PatchResponse = {
    /**
     * Patch Id
     */
    patch_id: number;
    /**
     * Patch Uid
     */
    patch_uid: string;
    /**
     * Label Class Id
     */
    label_class_id: number;
    /**
     * Image Id
     */
    image_id: number;
    /**
     * Downsample Factor
     */
    downsample_factor: number;
    /**
     * Centroid X
     */
    centroid_x?: number | null;
    /**
     * Centroid Y
     */
    centroid_y?: number | null;
    /**
     * Polygon
     */
    polygon?: string | null;
    /**
     * Embed X
     */
    embed_x?: number | null;
    /**
     * Embed Y
     */
    embed_y?: number | null;
    /**
     * Grid Cell I
     */
    grid_cell_i?: number | null;
    /**
     * Grid Cell J
     */
    grid_cell_j?: number | null;
    /**
     * Pred Label Class Id
     */
    pred_label_class_id?: number | null;
    /**
     * Event Ts
     */
    event_ts?: string | null;
    /**
     * Priority
     */
    priority?: number | null;
};
/**
 * ProjectResponse
 */
export type ProjectResponse = {
    /**
     * Project Id
     */
    project_id: number;
    /**
     * Project Name
     */
    project_name: string;
    /**
     * Description
     */
    description?: string | null;
};
/**
 * SumOver
 */
export type SumOver = 'gt' | 'pred';
/**
 * ValidationError
 */
export type ValidationError = {
    /**
     * Location
     */
    loc: Array<string | number>;
    /**
     * Message
     */
    msg: string;
    /**
     * Error Type
     */
    type: string;
    /**
     * Input
     */
    input?: unknown;
    /**
     * Context
     */
    ctx?: {
        [key: string]: unknown;
    };
};
/**
 * WorldInfo
 */
export type WorldInfo = {
    /**
     * World
     */
    world: {
        [key: string]: unknown;
    };
    /**
     * Osm Zoom Offset
     */
    osm_zoom_offset: number;
    /**
     * Max Level
     */
    max_level: number;
};
export type InfoProjectsProjectIdInfoGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
    };
    query?: never;
    url: '/projects/{project_id}/info';
};
export type InfoProjectsProjectIdInfoGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type InfoProjectsProjectIdInfoGetError = InfoProjectsProjectIdInfoGetErrors[keyof InfoProjectsProjectIdInfoGetErrors];
export type InfoProjectsProjectIdInfoGetResponses = {
    /**
     * Successful Response
     */
    200: WorldInfo;
};
export type InfoProjectsProjectIdInfoGetResponse = InfoProjectsProjectIdInfoGetResponses[keyof InfoProjectsProjectIdInfoGetResponses];
export type ServeTileProjectsProjectIdTilesZxyPngGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
        /**
         * Z
         */
        z: number;
        /**
         * X
         */
        x: number;
        /**
         * Y
         */
        y: number;
    };
    query?: {
        sum_over?: SumOver;
        /**
         * Lp
         */
        lp?: Array<string> | null;
    };
    url: '/projects/{project_id}/tiles/{z}/{x}/{y}.png';
};
export type ServeTileProjectsProjectIdTilesZxyPngGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ServeTileProjectsProjectIdTilesZxyPngGetError = ServeTileProjectsProjectIdTilesZxyPngGetErrors[keyof ServeTileProjectsProjectIdTilesZxyPngGetErrors];
export type ServeTileProjectsProjectIdTilesZxyPngGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type GetConfusionMatrixProjectsProjectIdConfusionMatrixGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
    };
    query: {
        /**
         * X Min
         */
        x_min: number;
        /**
         * Y Min
         */
        y_min: number;
        /**
         * X Max
         */
        x_max: number;
        /**
         * Y Max
         */
        y_max: number;
        /**
         * Lp
         */
        lp?: Array<string> | null;
    };
    url: '/projects/{project_id}/confusion_matrix';
};
export type GetConfusionMatrixProjectsProjectIdConfusionMatrixGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetConfusionMatrixProjectsProjectIdConfusionMatrixGetError = GetConfusionMatrixProjectsProjectIdConfusionMatrixGetErrors[keyof GetConfusionMatrixProjectsProjectIdConfusionMatrixGetErrors];
export type GetConfusionMatrixProjectsProjectIdConfusionMatrixGetResponses = {
    /**
     * Successful Response
     */
    200: ConfusionMatrixResponse;
};
export type GetConfusionMatrixProjectsProjectIdConfusionMatrixGetResponse = GetConfusionMatrixProjectsProjectIdConfusionMatrixGetResponses[keyof GetConfusionMatrixProjectsProjectIdConfusionMatrixGetResponses];
export type ListProjectsProjectsGetData = {
    body?: never;
    path?: never;
    query?: never;
    url: '/projects/';
};
export type ListProjectsProjectsGetResponses = {
    /**
     * Response List Projects Projects  Get
     *
     * Successful Response
     */
    200: Array<ProjectResponse>;
};
export type ListProjectsProjectsGetResponse = ListProjectsProjectsGetResponses[keyof ListProjectsProjectsGetResponses];
export type GetProjectProjectsProjectIdGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
    };
    query?: never;
    url: '/projects/{project_id}';
};
export type GetProjectProjectsProjectIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetProjectProjectsProjectIdGetError = GetProjectProjectsProjectIdGetErrors[keyof GetProjectProjectsProjectIdGetErrors];
export type GetProjectProjectsProjectIdGetResponses = {
    /**
     * Successful Response
     */
    200: ProjectResponse;
};
export type GetProjectProjectsProjectIdGetResponse = GetProjectProjectsProjectIdGetResponses[keyof GetProjectProjectsProjectIdGetResponses];
export type ListLabelClassesProjectsProjectIdLabelClassesGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
    };
    query?: never;
    url: '/projects/{project_id}/label_classes/';
};
export type ListLabelClassesProjectsProjectIdLabelClassesGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListLabelClassesProjectsProjectIdLabelClassesGetError = ListLabelClassesProjectsProjectIdLabelClassesGetErrors[keyof ListLabelClassesProjectsProjectIdLabelClassesGetErrors];
export type ListLabelClassesProjectsProjectIdLabelClassesGetResponses = {
    /**
     * Response List Label Classes Projects  Project Id  Label Classes  Get
     *
     * Successful Response
     */
    200: Array<LabelClassResponse>;
};
export type ListLabelClassesProjectsProjectIdLabelClassesGetResponse = ListLabelClassesProjectsProjectIdLabelClassesGetResponses[keyof ListLabelClassesProjectsProjectIdLabelClassesGetResponses];
export type GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
        /**
         * Label Class Id
         */
        label_class_id: number;
    };
    query?: never;
    url: '/projects/{project_id}/label_classes/{label_class_id}';
};
export type GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetError = GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetErrors[keyof GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetErrors];
export type GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetResponses = {
    /**
     * Successful Response
     */
    200: LabelClassResponse;
};
export type GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetResponse = GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetResponses[keyof GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetResponses];
export type ListPatchesProjectsProjectIdPatchesGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
    };
    query?: {
        /**
         * Cursor
         *
         * Keyset cursor: last seen patch_id (exclusive lower bound)
         */
        cursor?: number;
        /**
         * Limit
         */
        limit?: number;
        /**
         * X Min
         */
        x_min?: number | null;
        /**
         * Y Min
         */
        y_min?: number | null;
        /**
         * X Max
         */
        x_max?: number | null;
        /**
         * Y Max
         */
        y_max?: number | null;
        /**
         * Lp
         *
         * Label pair filter: repeat for each pair as 'gt,pred' (e.g. lp=0,1&lp=2,2)
         */
        lp?: Array<string> | null;
    };
    url: '/projects/{project_id}/patches/';
};
export type ListPatchesProjectsProjectIdPatchesGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type ListPatchesProjectsProjectIdPatchesGetError = ListPatchesProjectsProjectIdPatchesGetErrors[keyof ListPatchesProjectsProjectIdPatchesGetErrors];
export type ListPatchesProjectsProjectIdPatchesGetResponses = {
    /**
     * Response List Patches Projects  Project Id  Patches  Get
     *
     * Successful Response
     */
    200: Array<PatchResponse>;
};
export type ListPatchesProjectsProjectIdPatchesGetResponse = ListPatchesProjectsProjectIdPatchesGetResponses[keyof ListPatchesProjectsProjectIdPatchesGetResponses];
export type AssignLabelsByIdsProjectsProjectIdPatchesPostData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
    };
    query: {
        /**
         * Patch Ids
         *
         * Patch IDs to relabel
         */
        patch_ids: Array<number>;
        /**
         * Label Class Id
         *
         * Ground-truth label class to assign
         */
        label_class_id: number;
    };
    url: '/projects/{project_id}/patches/';
};
export type AssignLabelsByIdsProjectsProjectIdPatchesPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AssignLabelsByIdsProjectsProjectIdPatchesPostError = AssignLabelsByIdsProjectsProjectIdPatchesPostErrors[keyof AssignLabelsByIdsProjectsProjectIdPatchesPostErrors];
export type AssignLabelsByIdsProjectsProjectIdPatchesPostResponses = {
    /**
     * Successful Response
     */
    200: LabelAssignResponse;
};
export type AssignLabelsByIdsProjectsProjectIdPatchesPostResponse = AssignLabelsByIdsProjectsProjectIdPatchesPostResponses[keyof AssignLabelsByIdsProjectsProjectIdPatchesPostResponses];
export type GetPatchProjectsProjectIdPatchesPatchIdGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
        /**
         * Patch Id
         */
        patch_id: number;
    };
    query?: never;
    url: '/projects/{project_id}/patches/{patch_id}';
};
export type GetPatchProjectsProjectIdPatchesPatchIdGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetPatchProjectsProjectIdPatchesPatchIdGetError = GetPatchProjectsProjectIdPatchesPatchIdGetErrors[keyof GetPatchProjectsProjectIdPatchesPatchIdGetErrors];
export type GetPatchProjectsProjectIdPatchesPatchIdGetResponses = {
    /**
     * Successful Response
     */
    200: PatchResponse;
};
export type GetPatchProjectsProjectIdPatchesPatchIdGetResponse = GetPatchProjectsProjectIdPatchesPatchIdGetResponses[keyof GetPatchProjectsProjectIdPatchesPatchIdGetResponses];
export type GetPatchImageProjectsProjectIdPatchesPatchIdImageGetData = {
    body?: never;
    path: {
        /**
         * Project Id
         */
        project_id: number;
        /**
         * Patch Id
         */
        patch_id: number;
    };
    query?: never;
    url: '/projects/{project_id}/patches/{patch_id}/image';
};
export type GetPatchImageProjectsProjectIdPatchesPatchIdImageGetErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type GetPatchImageProjectsProjectIdPatchesPatchIdImageGetError = GetPatchImageProjectsProjectIdPatchesPatchIdImageGetErrors[keyof GetPatchImageProjectsProjectIdPatchesPatchIdImageGetErrors];
export type GetPatchImageProjectsProjectIdPatchesPatchIdImageGetResponses = {
    /**
     * Successful Response
     */
    200: unknown;
};
export type AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostData = {
    body: LabelAssignByPolygonRequest;
    path: {
        /**
         * Project Id
         */
        project_id: number;
    };
    query: {
        /**
         * Label Class Id
         *
         * Ground-truth label class to assign
         */
        label_class_id: number;
        /**
         * Lp
         *
         * Label pair filter: repeat for each pair as 'gt,pred' (e.g. lp=0,1&lp=2,2)
         */
        lp?: Array<string> | null;
    };
    url: '/projects/{project_id}/patches/polygonassign';
};
export type AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostErrors = {
    /**
     * Validation Error
     */
    422: HttpValidationError;
};
export type AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostError = AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostErrors[keyof AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostErrors];
export type AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostResponses = {
    /**
     * Successful Response
     */
    200: LabelAssignResponse;
};
export type AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostResponse = AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostResponses[keyof AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostResponses];
