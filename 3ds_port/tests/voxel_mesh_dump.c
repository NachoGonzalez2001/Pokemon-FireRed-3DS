/* The terrain of one map as the game builds it, dumped for the relief
 * checker (scripts/voxel_relief_lines.py): the actual C emitter run over the
 * whole layout with the shipped relief.bin and buildings.bin, every vertex
 * written out.
 *
 *     voxel_mesh_dump IN OUT [all]
 *
 * IN (written by the checker): u16 layout id (1-based, gMapLayouts order),
 * u16 width, u16 height, then width*height u16 metatile ids.
 * OUT: u32 vertex count, then per vertex float x, y, z, u, v, shade.
 *
 * With `all` (scripts/voxel_view.py) the whole map as the game draws it. IN
 * goes on: u16 1 indoor or 2 cave, u16 primary tileset is General, u16 border[4], char
 * secondary tileset symbol[64]. OUT: u32 terrain, tree and model vertex counts,
 * their vertices, the graded tree texture and the layout's model page (u32
 * width, u32 height, row-major RGBA5551; 0 by 0 without a page), then the
 * grade of every BGR555 colour (32768 u16).
 *
 * The atlas is a virtual one: id i sits in slot i of a 64x64 grid of slots,
 * so a triangle's UVs give back the atlas id it samples and the texel within
 * it (VOXEL_CUT_FIRST + k: cut variant k; VOXEL_METATILE_REAL + i: ground
 * variant i). Every cell is ground (the sea lies flush with it anyway). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "voxel_mesh_builder.h"
#include "voxel_regions.h"
#include "voxel_atlas.h"
#include "voxel_building.h"
#include "voxel_relief.h"
#include "voxel_sign.h"
#include "voxel_tree.h"
#include "voxel_grade.h"
#include "3ds_video.h"

#define GRID 64u

/* The tilesets the props and woods are found by: only their addresses count. */
#define TILESETS(X) X(ViridianForest) X(FuchsiaCity) X(BerryForest) X(PalletTown) \
    X(LavenderTown) X(ViridianCity) X(VermilionCity) X(SeviiIslands45) X(SeviiIslands123) \
    X(SeafoamIslands) X(SaffronCity) X(RockTunnel) X(NavelRock) X(MtEmber) X(IndigoPlateau) \
    X(DiglettsCave) X(CeruleanCity) X(CeruleanCave) X(Cave) X(CeladonCity) X(SeviiIslands67) X(SilphCo) X(PokemonMansion) X(VermilionGym)
#define DEFINE(name) const char gTileset_##name[4];
TILESETS(DEFINE)
static const char sOtherTileset[4];

static const void *TilesetNamed(const char *symbol)
{
#define MATCH(name) if (strcmp(symbol, "gTileset_" #name) == 0) return gTileset_##name;
    TILESETS(MATCH)
    return sOtherTileset;
}

static VoxelMapInstance sMap;
static VoxelAtlasMap sAtlas;
static uint16_t *sCells;
static uint16_t sBorder[4];
static bool sHasBorder, sTreeSprites;

unsigned VoxelRegions_RoleAt(unsigned id, int x, int y)
{
    (void)id; (void)x; (void)y;
    return VOXEL_ROLE_FLOOR;
}
bool VoxelWorld_UsesTreeSprites(const VoxelMapInstance *m) { (void)m; return sTreeSprites; }
unsigned VoxelWorld_InstanceCount(void) { return 1; }
bool VoxelWorld_BorderIsWater(int x, int y) { (void)x; (void)y; return false; }
const VoxelMapInstance *VoxelWorld_Instance(unsigned i) { return i == 0 ? &sMap : NULL; }
const VoxelMapInstance *VoxelWorld_GetInstanceAt(int x, int y)
{
    return x >= 0 && y >= 0 && x < sMap.width && y < sMap.height ? &sMap : NULL;
}
int VoxelWorld_GetMetatileId(int x, int y)
{
    if (!VoxelWorld_GetInstanceAt(x, y))
        return -1;
    return sCells[y * sMap.width + x];
}
VoxelVisualShape VoxelWorld_ClassifyTile(int x, int y)
{
    return VoxelWorld_GetInstanceAt(x, y) ? VOXEL_SHAPE_FLAT : VOXEL_SHAPE_VOID;
}
int VoxelWorld_BorderMetatile(int x, int y)
{
    /* voxel_world.c's, MAP_OFFSET being 7 */
    return sHasBorder ? sBorder[((x + 8) & 1) + (((y + 8) & 1) * 2)] : -1;
}
void VoxelWorld_GetPlayerWorldCoords(float *x, float *z) { *x = 0; *z = 0; }
void VoxelAtlas_SlotUV(unsigned slot, float *u, float *v, float *ue, float *ve)
{
    *u = (slot % GRID) / (float)GRID; *ue = *u + 1.0f / GRID;
    *v = (slot / GRID) / (float)GRID; *ve = *v + 1.0f / GRID;
}
void VoxelAtlas_SolidUV(VoxelSolidColor c, float *u, float *v, float *ue, float *ve)
{
    VoxelAtlas_SlotUV(GRID * GRID - 1 - (unsigned)c, u, v, ue, ve);
}

/* A texture in PICA order, graded as it is on the console, written row by row. */
static void WriteTexture(FILE *out, uint16_t *texels, uint32_t w, uint32_t h)
{
    uint16_t *row = malloc(w * 2 + 2);

    fwrite(&w, 4, 1, out);
    fwrite(&h, 4, 1, out);
    VoxelGrade_Texels(texels, w * h);
    for (uint32_t y = 0; y < h; ++y)
    {
        for (uint32_t x = 0; x < w; ++x)
            row[x] = texels[CtrVideo_Texel(x, y, w)];
        fwrite(row, 2, w, out);
    }
    free(row);
}

static int DumpAll(FILE *out, const VoxelBuilder *b, uint32_t terrain, uint32_t trees)
{
    uint32_t counts[3] = { terrain, trees - terrain, b->count - trees };
    uint16_t *tex = malloc(VOXEL_TREE_TEXTURE_DIM * VOXEL_TREE_TEXTURE_H * 2);
    FILE *in = fopen("romfs/" VOXEL_TREE_TEXTURE_PATH, "rb");
    unsigned w = 0, h = 0;
    int page = VoxelBuildings_PageOf(&sMap);

    if (in == NULL || fread(tex, 2, VOXEL_TREE_TEXTURE_DIM * VOXEL_TREE_TEXTURE_H, in)
                      != VOXEL_TREE_TEXTURE_DIM * VOXEL_TREE_TEXTURE_H)
        return 3;
    fclose(in);
    fwrite(counts, 4, 3, out);
    for (unsigned i = 0; i < b->count; ++i)
    {
        const VoxelVertex *v = &b->vertices[i];
        float f[6] = { v->x, v->y, v->z, v->u, v->v, v->shade };
        fwrite(f, 4, 6, out);
    }
    WriteTexture(out, tex, VOXEL_TREE_TEXTURE_DIM, VOXEL_TREE_TEXTURE_H);
    free(tex);
    if (page < 0 || !VoxelBuildings_PageSize((unsigned)page, &w, &h))
        w = h = 0;
    tex = malloc(w * h * 2 + 2);
    if (w)
        VoxelBuildings_ReadPage((unsigned)page, 0, w * h, tex);
    WriteTexture(out, tex, w, h);
    free(tex);
    for (uint32_t c = 0; c < 32768; ++c)
    {
        uint16_t graded = VoxelGrade_RGBA5551((uint16_t)c);

        fwrite(&graded, 2, 1, out);
    }
    return 0;
}

int main(int argc, char **argv)
{
    static VoxelVertex verts[3000000];
    VoxelBuilder b;
    FILE *in, *out;
    uint16_t head[3];
    uint32_t count;

    if (argc < 3 || (in = fopen(argv[1], "rb")) == NULL)
        return 2;
    if (fread(head, 2, 3, in) != 3)
        return 2;
    sMap.layoutId = head[0];
    sMap.width = head[1];
    sMap.height = head[2];
    sCells = malloc((size_t)head[1] * head[2] * 2);
    if (fread(sCells, 2, (size_t)head[1] * head[2], in) != (size_t)head[1] * head[2])
        return 2;
    if (argc > 3)
    {
        uint16_t flags[2];
        char secondary[64];

        if (fread(flags, 2, 2, in) != 2 || fread(sBorder, 2, 4, in) != 4 || fread(secondary, 1, 64, in) != 64)
            return 2;
        sMap.indoor = flags[0] == 1;
        sMap.cave = flags[0] == 2;
        sTreeSprites = !sMap.indoor && flags[1] != 0;
        sHasBorder = true;
        secondary[63] = 0;
        sMap.secondaryTileset = TilesetNamed(secondary);
        VoxelGrade_Init();
    }
    fclose(in);
    for (unsigned i = 0; i < VOXEL_METATILE_IDS; ++i)
        sAtlas.slotOf[i] = (uint16_t)(i + 1);
    if (!VoxelRelief_Init())
        return 3;
    VoxelBuildings_Init();
    VoxelSign_Init();
    VoxelBuilder_Init(&b, verts, sizeof(verts) / sizeof(verts[0]));
    VoxelBuilder_SetAtlas(&b, &sAtlas);
    VoxelBuilder_SetOrigin(&b, 0, 0);
    VoxelMesh_BeginWindow(0, 0, sMap.width, sMap.height);
    VoxelMesh_EmitInstance(&b, &sMap, 0, 0, sMap.width, sMap.height);
    if ((out = fopen(argv[2], "wb")) == NULL)
        return 2;
    if (argc > 3)
    {
        const int reach = 12;
        uint32_t terrain, trees;
        int code;

        VoxelMesh_EmitBorder(&b, -reach, -reach, sMap.width + reach, sMap.height + reach);
        terrain = b.count;
        VoxelTree_EmitInstance(&b, &sMap, 0, 0, sMap.width, sMap.height);
        VoxelTree_EmitBorder(&b, -reach, -reach, sMap.width + reach, sMap.height + reach);
        trees = b.count;
        VoxelBuildings_EmitInstance(&b, &sMap, 0, 0, sMap.width, sMap.height);
        code = DumpAll(out, &b, terrain, trees);
        fclose(out);
        printf("%u vertices, %u dropped, %u uncovered\n", b.count, b.dropped, b.uncovered);
        return code;
    }
    count = b.count;
    fwrite(&count, 4, 1, out);
    for (unsigned i = 0; i < b.count; ++i)
    {
        const VoxelVertex *v = &b.vertices[i];
        float f[6] = { v->x, v->y, v->z, v->u, v->v, v->shade };
        fwrite(f, 4, 6, out);
    }
    fclose(out);
    printf("%u vertices, %u dropped, %u uncovered\n", b.count, b.dropped, b.uncovered);
    return 0;
}
