import type { Client, Options as Options2, TDataShape } from './client';
import type { AssignLabelsByIdsProjectsProjectIdPatchesPostData, AssignLabelsByIdsProjectsProjectIdPatchesPostErrors, AssignLabelsByIdsProjectsProjectIdPatchesPostResponses, AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostData, AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostErrors, AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostResponses, GetConfusionMatrixProjectsProjectIdConfusionMatrixGetData, GetConfusionMatrixProjectsProjectIdConfusionMatrixGetErrors, GetConfusionMatrixProjectsProjectIdConfusionMatrixGetResponses, GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetData, GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetErrors, GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetResponses, GetPatchImageProjectsProjectIdPatchesPatchIdImageGetData, GetPatchImageProjectsProjectIdPatchesPatchIdImageGetErrors, GetPatchImageProjectsProjectIdPatchesPatchIdImageGetResponses, GetPatchProjectsProjectIdPatchesPatchIdGetData, GetPatchProjectsProjectIdPatchesPatchIdGetErrors, GetPatchProjectsProjectIdPatchesPatchIdGetResponses, GetProjectProjectsProjectIdGetData, GetProjectProjectsProjectIdGetErrors, GetProjectProjectsProjectIdGetResponses, InfoProjectsProjectIdInfoGetData, InfoProjectsProjectIdInfoGetErrors, InfoProjectsProjectIdInfoGetResponses, ListLabelClassesProjectsProjectIdLabelClassesGetData, ListLabelClassesProjectsProjectIdLabelClassesGetErrors, ListLabelClassesProjectsProjectIdLabelClassesGetResponses, ListPatchesProjectsProjectIdPatchesGetData, ListPatchesProjectsProjectIdPatchesGetErrors, ListPatchesProjectsProjectIdPatchesGetResponses, ListProjectsProjectsGetData, ListProjectsProjectsGetResponses, ServeTileProjectsProjectIdTilesZxyPngGetData, ServeTileProjectsProjectIdTilesZxyPngGetErrors, ServeTileProjectsProjectIdTilesZxyPngGetResponses } from './types.gen';
export type Options<TData extends TDataShape = TDataShape, ThrowOnError extends boolean = boolean, TResponse = unknown> = Options2<TData, ThrowOnError, TResponse> & {
    /**
     * You can provide a client instance returned by `createClient()` instead of
     * individual options. This might be also useful if you want to implement a
     * custom client.
     */
    client?: Client;
    /**
     * You can pass arbitrary values through the `meta` object. This can be
     * used to access values that aren't defined as part of the SDK function.
     */
    meta?: Record<string, unknown>;
};
/**
 * Info
 */
export declare const infoProjectsProjectIdInfoGet: <ThrowOnError extends boolean = false>(options: Options<InfoProjectsProjectIdInfoGetData, ThrowOnError>) => import("./client").RequestResult<InfoProjectsProjectIdInfoGetResponses, InfoProjectsProjectIdInfoGetErrors, ThrowOnError, "fields">;
/**
 * Serve Tile
 */
export declare const serveTileProjectsProjectIdTilesZXYPngGet: <ThrowOnError extends boolean = false>(options: Options<ServeTileProjectsProjectIdTilesZxyPngGetData, ThrowOnError>) => import("./client").RequestResult<ServeTileProjectsProjectIdTilesZxyPngGetResponses, ServeTileProjectsProjectIdTilesZxyPngGetErrors, ThrowOnError, "fields">;
/**
 * Get Confusion Matrix
 */
export declare const getConfusionMatrixProjectsProjectIdConfusionMatrixGet: <ThrowOnError extends boolean = false>(options: Options<GetConfusionMatrixProjectsProjectIdConfusionMatrixGetData, ThrowOnError>) => import("./client").RequestResult<GetConfusionMatrixProjectsProjectIdConfusionMatrixGetResponses, GetConfusionMatrixProjectsProjectIdConfusionMatrixGetErrors, ThrowOnError, "fields">;
/**
 * List Projects
 */
export declare const listProjectsProjectsGet: <ThrowOnError extends boolean = false>(options?: Options<ListProjectsProjectsGetData, ThrowOnError>) => import("./client").RequestResult<ListProjectsProjectsGetResponses, unknown, ThrowOnError, "fields">;
/**
 * Get Project
 */
export declare const getProjectProjectsProjectIdGet: <ThrowOnError extends boolean = false>(options: Options<GetProjectProjectsProjectIdGetData, ThrowOnError>) => import("./client").RequestResult<GetProjectProjectsProjectIdGetResponses, GetProjectProjectsProjectIdGetErrors, ThrowOnError, "fields">;
/**
 * List Label Classes
 */
export declare const listLabelClassesProjectsProjectIdLabelClassesGet: <ThrowOnError extends boolean = false>(options: Options<ListLabelClassesProjectsProjectIdLabelClassesGetData, ThrowOnError>) => import("./client").RequestResult<ListLabelClassesProjectsProjectIdLabelClassesGetResponses, ListLabelClassesProjectsProjectIdLabelClassesGetErrors, ThrowOnError, "fields">;
/**
 * Get Label Class
 */
export declare const getLabelClassProjectsProjectIdLabelClassesLabelClassIdGet: <ThrowOnError extends boolean = false>(options: Options<GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetData, ThrowOnError>) => import("./client").RequestResult<GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetResponses, GetLabelClassProjectsProjectIdLabelClassesLabelClassIdGetErrors, ThrowOnError, "fields">;
/**
 * List Patches
 */
export declare const listPatchesProjectsProjectIdPatchesGet: <ThrowOnError extends boolean = false>(options: Options<ListPatchesProjectsProjectIdPatchesGetData, ThrowOnError>) => import("./client").RequestResult<ListPatchesProjectsProjectIdPatchesGetResponses, ListPatchesProjectsProjectIdPatchesGetErrors, ThrowOnError, "fields">;
/**
 * Assign Labels By Ids
 */
export declare const assignLabelsByIdsProjectsProjectIdPatchesPost: <ThrowOnError extends boolean = false>(options: Options<AssignLabelsByIdsProjectsProjectIdPatchesPostData, ThrowOnError>) => import("./client").RequestResult<AssignLabelsByIdsProjectsProjectIdPatchesPostResponses, AssignLabelsByIdsProjectsProjectIdPatchesPostErrors, ThrowOnError, "fields">;
/**
 * Get Patch
 */
export declare const getPatchProjectsProjectIdPatchesPatchIdGet: <ThrowOnError extends boolean = false>(options: Options<GetPatchProjectsProjectIdPatchesPatchIdGetData, ThrowOnError>) => import("./client").RequestResult<GetPatchProjectsProjectIdPatchesPatchIdGetResponses, GetPatchProjectsProjectIdPatchesPatchIdGetErrors, ThrowOnError, "fields">;
/**
 * Get Patch Image
 */
export declare const getPatchImageProjectsProjectIdPatchesPatchIdImageGet: <ThrowOnError extends boolean = false>(options: Options<GetPatchImageProjectsProjectIdPatchesPatchIdImageGetData, ThrowOnError>) => import("./client").RequestResult<GetPatchImageProjectsProjectIdPatchesPatchIdImageGetResponses, GetPatchImageProjectsProjectIdPatchesPatchIdImageGetErrors, ThrowOnError, "fields">;
/**
 * Assign Labels By Polygon
 */
export declare const assignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPost: <ThrowOnError extends boolean = false>(options: Options<AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostData, ThrowOnError>) => import("./client").RequestResult<AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostResponses, AssignLabelsByPolygonProjectsProjectIdPatchesPolygonassignPostErrors, ThrowOnError, "fields">;
