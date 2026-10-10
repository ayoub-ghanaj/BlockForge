package builderverify;

import com.google.gson.*;
import com.moulberry.axiom.blueprint.BlueprintIo;
import com.moulberry.axiom.blueprint.RawBlueprint;
import com.sk89q.worldedit.extent.clipboard.io.BuiltInClipboardFormat;
import com.sk89q.worldedit.math.BlockVector3;
import fi.dy.masa.litematica.schematic.LitematicaSchematic;
import net.fabricmc.api.ClientModInitializer;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;
import net.minecraft.commands.arguments.blocks.BlockStateParser;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.Difficulty;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.level.*;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.gamerules.GameRules;
import net.minecraft.world.level.levelgen.WorldOptions;
import net.minecraft.world.level.levelgen.presets.WorldPresets;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.BooleanOp;
import java.nio.file.*;
import java.util.*;

/** Development test mod. Runs only with an explicit JVM verification property. */
public final class BuilderVerify implements ClientModInitializer {
    private Path directory;
    private final JsonObject report=new JsonObject();
    private final List<Fixture> fixtures=new ArrayList<>();
    private final List<ProtectionCheck> protectionChecks=new ArrayList<>();
    private final String worldName=System.getProperty("minecraft_builder.world","Builder_Integration_Test");
    record Fixture(String name,int sx,int sy,int sz,BlockState[] blocks,JsonObject perimeter) {
        BlockState at(int x,int y,int z) {return blocks[x+sx*(z+sz*y)];}
    }
    record ProtectionCheck(Fixture fixture,int originX) {}
    @Override public void onInitializeClient() {
        String path=System.getProperty("minecraft_builder.verify");
        if(path==null)return;
        directory=Path.of(path);
        Thread worker=new Thread(()->{
            try {
                for(int i=0;i<180;i++) {
                    Thread.sleep(1000);
                    Minecraft mc=Minecraft.getInstance();
                    if(mc!=null && mc.screen!=null && mc.getOverlay()==null) {
                        Thread.sleep(3000);
                        mc.execute(()->{try {createWorld();}catch(Throwable t){fail(t);}});
                        return;
                    }
                }
                throw new IllegalStateException("Timed out waiting for client startup");
            }catch(Throwable t){fail(t);}
        },"Builder verification startup");
        worker.setDaemon(true);worker.start();
    }
    private static void check(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
    private static BlockState parse(String state) throws Exception {
        return BlockStateParser.parseForBlock(BuiltInRegistries.BLOCK,state,false).blockState();
    }
    private JsonElement json(String file) throws Exception {
        return JsonParser.parseString(Files.readString(directory.resolve(file)));
    }
    private void checkImports() throws Exception {
        JsonArray cases=json("cases.json").getAsJsonArray();
        JsonArray passed=new JsonArray();
        for(JsonElement c:cases) {
            String name=c.getAsString();JsonObject doc=json(name+".json").getAsJsonObject();
            JsonArray size=doc.getAsJsonArray("size");
            int sx=size.get(0).getAsInt(),sy=size.get(1).getAsInt(),sz=size.get(2).getAsInt();
            BlockState[] expected=new BlockState[sx*sy*sz];Arrays.fill(expected,Blocks.AIR.defaultBlockState());
            List<BlockState> palette=new ArrayList<>();
            for(JsonElement state:doc.getAsJsonArray("palette"))palette.add(parse(state.getAsString()));
            for(JsonElement cell:doc.getAsJsonArray("cells")) {
                JsonArray p=cell.getAsJsonArray();
                expected[p.get(0).getAsInt()+sx*(p.get(2).getAsInt()+sz*p.get(1).getAsInt())]=palette.get(p.get(3).getAsInt());
            }
            Fixture fixture=new Fixture(name,sx,sy,sz,expected,doc.getAsJsonObject("perimeter"));
            boolean sparse=expected.length>1_000_000;int compared=0;
            var lite=LitematicaSchematic.createFromFile(directory,name+".litematic");
            check(lite!=null,"Litematica rejected "+name);
            var container=lite.getSubRegionContainer("Build");
            check(container!=null,"Litematica region missing");
            check(container.getSize().equals(new BlockPos(sx,sy,sz)),"Litematica size mismatch");
            RawBlueprint bp;
            try(var input=Files.newInputStream(directory.resolve(name+".bp"))) {bp=BlueprintIo.readRawBlueprint(input);}
            try(var input=Files.newInputStream(directory.resolve(name+".schem"));
                var reader=BuiltInClipboardFormat.SPONGE_V2_SCHEMATIC.getReader(input)) {
                var clipboard=reader.read();
                check(clipboard.getDimensions().equals(BlockVector3.at(sx,sy,sz)),"WorldEdit size mismatch");
                var parsedStates=new HashMap<String,BlockState>();
                for(int y=0;y<sy;y++)for(int z=0;z<sz;z++)for(int x=0;x<sx;x++) {
                    BlockState want=fixture.at(x,y,z);
                    int linear=x+sx*(z+sz*y);
                    if(sparse && want.isAir() && linear%Math.max(1,expected.length/4096)!=0 && linear!=expected.length-1)continue;
                    compared++;String pos=name+" at "+x+","+y+","+z;
                    check(container.get(x,y,z)==want,"Litematica mismatch "+pos+" want="+want+" got="+container.get(x,y,z));
                    var section=bp.blocks().get(BlockPos.asLong(x>>4,y>>4,z>>4));
                    check(section!=null && section.get(x&15,y&15,z&15)==want,"Axiom mismatch "+pos);
                    String stateString=clipboard.getBlock(BlockVector3.at(x,y,z)).getAsString();
                    var worldedit=parsedStates.get(stateString);
                    if(worldedit==null) {worldedit=parse(stateString);parsedStates.put(stateString,worldedit);}
                    check(worldedit==want,"WorldEdit mismatch "+pos+" want="+want+" got="+worldedit);
                }
            }
            JsonObject result=new JsonObject();result.addProperty("name",name);result.addProperty("cellsComparedPerFormat",compared);
            result.addProperty("boundingCells",expected.length);
            result.addProperty("comparison",sparse?"every non-air block plus deterministic empty-cell samples":"every cell including air");
            boolean place=!sparse && Math.max(sx,sz)<=128;
            result.addProperty("placedInWorld",place && !name.startsWith("packing_"));
            result.addProperty("nonAirBlocks",doc.getAsJsonArray("cells").size());passed.add(result);
            if(place)fixtures.add(fixture);
            System.out.println("BUILDER_IMPORT_PASS "+name+" "+compared+" cells x 3 formats");
        }
        report.add("imports",passed);
        if(Files.exists(directory.resolve("incompatible-inputs.json"))) {
            JsonArray diagnoses=new JsonArray();
            for(JsonElement input:json("incompatible-inputs.json").getAsJsonArray()) {
                JsonObject row=input.getAsJsonObject();String file=row.get("file").getAsString();
                var lite=LitematicaSchematic.createFromFile(directory,file);
                check(lite!=null,"Original Litematica file could not be examined: "+file);
                var container=lite.getSubRegionContainer("Build");int missing=0;
                for(JsonElement element:row.getAsJsonArray("expected_missing")) {
                    JsonArray pos=element.getAsJsonArray();
                    check(container.get(pos.get(0).getAsInt(),pos.get(1).getAsInt(),pos.get(2).getAsInt()).isAir(),
                          "Unknown material did not become air: "+file+" "+pos);
                    missing++;
                }
                JsonObject diagnosis=new JsonObject();diagnosis.addProperty("file",file);
                diagnosis.addProperty("unavailableBlocksLoadedAsAir",missing);diagnoses.add(diagnosis);
                System.out.println("BUILDER_MISSING_BLOCKS_CONFIRMED "+file+" "+missing);
            }
            report.add("originalLitematicaDiagnostics",diagnoses);
        }
        int shapeCount=0;JsonArray shapeMismatches=new JsonArray(),nonSturdyTops=new JsonArray();
        for(JsonElement element:json("shape-cases.json").getAsJsonArray()) {
            JsonObject row=element.getAsJsonObject();BlockState state=parse(row.get("state").getAsString());
            int mask=0;
            var boxes=state.getShape(EmptyBlockGetter.INSTANCE,BlockPos.ZERO).toAabbs();
            for(int y=0;y<2;y++)for(int z=0;z<2;z++)for(int x=0;x<2;x++) {
                for(var box:boxes)if(box.contains((x+0.5)/2,(y+0.5)/2,(z+0.5)/2)) {mask|=1<<(x+2*z+4*y);break;}
            }
            var expectedShape=Shapes.empty();int expectedMask=row.get("mask").getAsInt();
            if((expectedMask&240)==240 && !state.isFaceSturdy(EmptyBlockGetter.INSTANCE,BlockPos.ZERO,net.minecraft.core.Direction.UP))
                nonSturdyTops.add(row.get("state").getAsString());
            for(int y=0;y<2;y++)for(int z=0;z<2;z++)for(int x=0;x<2;x++) {
                if((expectedMask&(1<<(x+2*z+4*y)))!=0)
                    expectedShape=Shapes.or(expectedShape,Shapes.box(x*.5,y*.5,z*.5,(x+1)*.5,(y+1)*.5,(z+1)*.5));
            }
            if(mask!=expectedMask || Shapes.joinIsNotEmpty(state.getShape(EmptyBlockGetter.INSTANCE,BlockPos.ZERO),expectedShape,BooleanOp.NOT_SAME)) {
                JsonObject mismatch=new JsonObject();mismatch.addProperty("state",row.get("state").getAsString());
                mismatch.addProperty("boxes",boxes.toString());shapeMismatches.add(mismatch);
            }
            shapeCount++;
        }
        report.addProperty("shapesComparedWithMinecraft",shapeCount);
        report.add("shapeMismatches",shapeMismatches);saveReport();
        report.add("nonSturdyTopStates",nonSturdyTops);
        check(shapeMismatches.isEmpty(),"Exact shape mismatches: "+shapeMismatches);
        report.addProperty("minecraft","26.1.2");
        report.addProperty("status","imports_passed");saveReport();
    }
    private void createWorld() throws Exception {
        Minecraft mc=Minecraft.getInstance();String name=worldName;
        if(Files.exists(mc.gameDirectory.toPath().resolve("saves").resolve(name).resolve("level.dat"))) {
            mc.createWorldOpenFlows().openWorld(name,()->{});
        }else {
            LevelSettings settings=new LevelSettings(name.replace('_',' '),GameType.CREATIVE,
                new LevelSettings.DifficultySettings(Difficulty.PEACEFUL,false,false),true,WorldDataConfiguration.DEFAULT);
            mc.createWorldOpenFlows().createFreshLevel(name,settings,new WorldOptions(20261003L,false,false),
                WorldPresets::createFlatWorldDimensions,mc.screen);
        }
        Thread worker=new Thread(()->{
            try {
                for(int i=0;i<180;i++) {
                    Thread.sleep(1000);
                    if(mc.level!=null && mc.player!=null && mc.getSingleplayerServer()!=null) {
                        mc.execute(()->{try {
                            checkImports();
                            mc.getSingleplayerServer().execute(()->{try {placeAndCheck();}catch(Throwable t){fail(t);}});
                        }catch(Throwable t){fail(t);}});return;
                    }
                }
                throw new IllegalStateException("Timed out entering test world");
            }catch(Throwable t){fail(t);}
        },"Builder test world");worker.setDaemon(true);worker.start();
    }
    private void placeAndCheck() throws Exception {
        Minecraft mc=Minecraft.getInstance();var server=mc.getSingleplayerServer();var level=server.overworld();
        level.getGameRules().set(GameRules.RANDOM_TICK_SPEED,0,server);
        level.getGameRules().set(GameRules.SPAWN_MOBS,false,server);
        level.getGameRules().set(GameRules.ADVANCE_TIME,false,server);
        server.getCommands().performPrefixedCommand(server.createCommandSourceStack(),"time set noon");
        int originX=0,checked=0,railUpdates=0;Fixture focus=null;int focusX=0;
        for(Fixture f:fixtures) {
            if(f.name.startsWith("packing_"))continue;
            server.getCommands().performPrefixedCommand(server.createCommandSourceStack(),
                "forceload add "+(originX-16)+" -16 "+(originX+f.sx+16)+" "+(f.sz+16));
            // Pumpkin/golem pattern checks inspect neighboring chunks on placement.
            for(int cx=(originX>>4)-1;cx<=((originX+f.sx)>>4)+1;cx++)
                for(int cz=-1;cz<=(f.sz>>4)+1;cz++)level.getChunk(cx,cz);
            for(int y=0;y<f.sy;y++)for(int z=0;z<f.sz;z++)for(int x=0;x<f.sx;x++)
                level.setBlock(new BlockPos(originX+x,0+y,z),f.at(x,y,z),2|16);
            for(int y=0;y<f.sy;y++)for(int z=0;z<f.sz;z++)for(int x=0;x<f.sx;x++) {
                BlockPos pos=new BlockPos(originX+x,y,z);
                BlockState actual=level.getBlockState(pos),expected=f.at(x,y,z);
                if(actual!=expected && expected.getBlock() instanceof net.minecraft.world.level.block.BaseRailBlock) {
                    check(actual.getBlock()==expected.getBlock() && actual.canSurvive(level,pos),"Rail failed to survive "+pos);
                    railUpdates++;
                } else check(actual==expected,"Placed state mismatch "+pos+" expected="+expected+" actual="+actual);
                checked++;
                if(f.at(x,y,z).getBlock() instanceof net.minecraft.world.level.block.StairBlock)
                    check(Block.updateFromNeighbourShapes(f.at(x,y,z),level,pos)==f.at(x,y,z),"Stair neighbor shape mismatch "+pos);
            }
            if(f.perimeter!=null)protectionChecks.add(new ProtectionCheck(f,originX));
            focus=f;focusX=originX;originX+=f.sx+12;
        }
        double targetX=focusX+focus.sx*0.5,targetY=focus.sy*0.48,targetZ=focus.sz*0.5;
        double distance=Math.max(focus.sy*1.7,focus.sx*1.3);
        if(Boolean.getBoolean("minecraft_builder.overview")) {
            targetX=(originX-12)*.5;targetY=fixtures.stream().mapToInt(f->f.sy).max().orElse(1)*.5;
            targetZ=fixtures.stream().mapToInt(f->f.sz).max().orElse(1)*.5;distance=(originX-12)*.85;
        }
        double cameraX=targetX+distance*0.5,cameraY=targetY+distance*(focus.perimeter!=null?.85:.28);
        double cameraZ=targetZ+(focus.name.endsWith("skull")?-distance:distance);
        float yaw=(float)Math.toDegrees(Math.atan2(cameraX-targetX,targetZ-cameraZ));
        float pitch=(float)Math.toDegrees(Math.atan2(cameraY-targetY,Math.hypot(cameraX-targetX,cameraZ-targetZ)));
        for(var player:server.getPlayerList().getPlayers()) {
            player.getAbilities().flying=true;player.onUpdateAbilities();
            player.teleportTo(level,cameraX,cameraY,cameraZ,Set.of(),yaw,pitch,false);
        }
        mc.execute(()->mc.options.renderDistance().set(12));
        server.saveEverything(false,true,true);
        report.addProperty("worldCellsVerified",checked);report.addProperty("railStatesAdjustedByMinecraft",railUpdates);report.addProperty("world",worldName);
        report.addProperty("status","world_placed_waiting_for_light");saveReport();
        Thread end=new Thread(()->{
            try {
                Thread.sleep(10000);
                server.execute(()->{try {checkProtection();}catch(Throwable t){fail(t);}});
                mc.execute(()->{mc.setScreen(null);mc.options.hideGui=true;});
                Thread.sleep(1000);
                mc.execute(()->Screenshot.grab(mc.gameDirectory,"builder-verification.png",mc.getMainRenderTarget(),1,c->System.out.println(c.getString())));
                Thread.sleep(3000);
                if(Boolean.getBoolean("minecraft_builder.keepOpen"))mc.execute(()->{mc.options.hideGui=false;});
                else mc.execute(mc::stop);
            }catch(Throwable t){fail(t);}
        },"Builder test finish");end.setDaemon(true);end.start();
    }
    private void checkProtection() throws Exception {
        var level=Minecraft.getInstance().getSingleplayerServer().overworld();
        int glass=0,lights=0,minimum=15,coverChecks=0,auditLights=0,auditCovers=0;JsonArray details=new JsonArray();
        for(ProtectionCheck item:protectionChecks) {
            Fixture f=item.fixture;JsonObject protection=f.perimeter.getAsJsonObject("protection");
            String mode=protection.get("mode").getAsString();int caseGlass=0,caseLights=0;
            BlockState coverState=protection.has("cover_state")&&!protection.get("cover_state").getAsString().isEmpty()?parse(protection.get("cover_state").getAsString()):null;
            for(int y=0;y<f.sy;y++)for(int z=0;z<f.sz;z++)for(int x=0;x<f.sx;x++) {
                if(coverState!=null && (mode.equals("GLASS")||mode.equals("BOTH")) && f.at(x,y,z)==coverState) {
                    BlockPos pos=new BlockPos(item.originX+x,y,z);
                    check(coverState.canSurvive(level,pos),"Cover has no valid support in "+f.name+" at "+pos);
                    for(BlockPos candidate:List.of(pos,pos.above()))for(EntityType<?> type:List.of(EntityType.ZOMBIE,EntityType.SLIME)) {
                        boolean allowed=net.minecraft.world.entity.SpawnPlacements.isSpawnPositionOk(type,level,candidate)
                            && level.noCollision(type.getSpawnAABB(candidate.getX()+.5,candidate.getY(),candidate.getZ()+.5));
                        check(!allowed,"Ground spawn possible on cover in "+f.name+" at "+candidate+": "+type);
                    }
                    coverChecks++;
                }
                String blockId=BuiltInRegistries.BLOCK.getKey(f.at(x,y,z).getBlock()).toString();
                if(f.at(x,y,z).is(Blocks.GLASS) || blockId.endsWith("_stained_glass")) {
                    BlockPos pos=new BlockPos(item.originX+x,y,z);BlockState state=level.getBlockState(pos);
                    check(!state.isValidSpawn(level,pos,EntityType.ZOMBIE),"Zombie valid on glass "+pos);
                    check(!state.isValidSpawn(level,pos,EntityType.SLIME),"Slime valid on glass "+pos);
                    caseGlass++;
                }
            }
            if(mode.equals("LIGHTS") || mode.equals("BOTH")) {
                for(JsonElement element:protection.getAsJsonArray("light_checks")) {
                    JsonArray p=element.getAsJsonArray();BlockPos pos=new BlockPos(item.originX+p.get(0).getAsInt(),p.get(1).getAsInt(),p.get(2).getAsInt());
                    int light=level.getBrightness(LightLayer.BLOCK,pos);
                    int threshold=protection.get("light_threshold").getAsInt();
                    check(light>=threshold,"Block light below "+threshold+" in "+f.name+" at "+pos+": "+light+" chunkLoaded="+level.hasChunkAt(pos));
                    minimum=Math.min(minimum,light);caseLights++;
                }
            }
            JsonObject detail=new JsonObject();detail.addProperty("name",f.name);detail.addProperty("glassSpawnPredicates",caseGlass*2);
            detail.addProperty("surfaceLightPositions",caseLights);details.add(detail);glass+=caseGlass;lights+=caseLights;
            if(f.perimeter.has("audit")) {
                JsonObject audit=f.perimeter.getAsJsonObject("audit");JsonArray origin=f.perimeter.getAsJsonArray("origin");
                for(JsonElement element:audit.getAsJsonArray("light_checks")) {
                    JsonArray p=element.getAsJsonArray();
                    BlockPos pos=new BlockPos(item.originX+p.get(0).getAsInt()-origin.get(0).getAsInt(),p.get(1).getAsInt()-origin.get(1).getAsInt(),p.get(2).getAsInt()-origin.get(2).getAsInt());
                    check(level.getBrightness(LightLayer.BLOCK,pos)>=audit.get("light_threshold").getAsInt(),"Edited protection light proof failed in "+f.name+" at "+pos);auditLights++;
                }
                for(JsonElement element:audit.getAsJsonArray("covered_checks")) {
                    JsonArray p=element.getAsJsonArray();
                    BlockPos pos=new BlockPos(item.originX+p.get(0).getAsInt()-origin.get(0).getAsInt(),p.get(1).getAsInt()-origin.get(1).getAsInt(),p.get(2).getAsInt()-origin.get(2).getAsInt());
                    check(level.getBlockState(pos).canSurvive(level,pos),"Edited protection cover has invalid support "+pos);
                    for(BlockPos candidate:List.of(pos,pos.above()))for(EntityType<?> type:List.of(EntityType.ZOMBIE,EntityType.SLIME)) {
                        boolean allowed=net.minecraft.world.entity.SpawnPlacements.isSpawnPositionOk(type,level,candidate)
                            && level.noCollision(type.getSpawnAABB(candidate.getX()+.5,candidate.getY(),candidate.getZ()+.5));
                        check(!allowed,"Edited protection cover permits ground spawn in "+f.name+" at "+candidate);
                    }
                    auditCovers++;
                }
            }
        }
        report.add("protection",details);report.addProperty("glassBlocksChecked",glass);
        report.addProperty("supportedCoverBlocksCheckedWithSpawnCollision",coverChecks);
        report.addProperty("editedAuditLightPositionsChecked",auditLights);report.addProperty("editedAuditCoverPositionsChecked",auditCovers);
        report.addProperty("surfaceLightsChecked",lights);if(lights>0)report.addProperty("minimumSurfaceBlockLight",minimum);
        report.add("groundCoverProbe",probeGroundCovers());
        var server=Minecraft.getInstance().getSingleplayerServer();
        server.getCommands().performPrefixedCommand(server.createCommandSourceStack(),"forceload remove all");
        report.addProperty("status","passed");saveReport();System.out.println("BUILDER_GAME_PASS "+report);
    }
    private JsonArray probeGroundCovers() throws Exception {
        var level=Minecraft.getInstance().getSingleplayerServer().overworld();JsonArray rows=new JsonArray();
        String[] covers={"glass","blue_stained_glass","oak_leaves[persistent=true,distance=7,waterlogged=false]",
            "white_carpet","stone_button[face=floor,facing=north,powered=false]",
            "oak_trapdoor[facing=north,half=bottom,open=false,powered=false,waterlogged=false]",
            "smooth_stone_slab[type=bottom,waterlogged=false]","rail[shape=north_south,waterlogged=false]",
            "stone_pressure_plate[powered=false]","redstone_wire[east=none,north=none,power=0,south=none,west=none]",
            "repeater[delay=1,facing=north,locked=false,powered=false]","comparator[facing=north,mode=compare,powered=false]",
            "lever[face=floor,facing=north,powered=false]"};
        String[] supports={"stone","smooth_stone_slab[type=bottom,waterlogged=false]",
            "smooth_stone_slab[type=top,waterlogged=false]","oak_stairs[facing=north,half=top,shape=straight,waterlogged=false]",
            "glass","tinted_glass","oak_leaves[persistent=true,distance=7,waterlogged=false]","slime_block","honey_block","soul_sand","ice"};
        int number=0;
        for(String cover:covers)for(String support:supports) {
            BlockPos pos=new BlockPos(-80+(number++%16)*3,8,(number/16)*3);
            BlockState state=parse("minecraft:"+cover),below=parse("minecraft:"+support);
            level.setBlock(pos.below(),below,2|16);level.setBlock(pos,state,2|16);
            level.setBlock(pos.above(),Blocks.AIR.defaultBlockState(),2|16);level.setBlock(pos.above(2),Blocks.AIR.defaultBlockState(),2|16);
            JsonObject row=new JsonObject();row.addProperty("cover",cover);row.addProperty("support",support);
            row.addProperty("survives",state.canSurvive(level,pos));
            boolean zombie=false,slime=false;
            for(BlockPos candidate:List.of(pos,pos.above())) {
                zombie|=net.minecraft.world.entity.SpawnPlacements.isSpawnPositionOk(EntityType.ZOMBIE,level,candidate)
                    && level.noCollision(EntityType.ZOMBIE.getSpawnAABB(candidate.getX()+.5,candidate.getY(),candidate.getZ()+.5));
                slime|=net.minecraft.world.entity.SpawnPlacements.isSpawnPositionOk(EntityType.SLIME,level,candidate)
                    && level.noCollision(EntityType.SLIME.getSpawnAABB(candidate.getX()+.5,candidate.getY(),candidate.getZ()+.5));
            }
            row.addProperty("zombieGroundPositionAllowed",zombie);row.addProperty("slimeGroundPositionAllowed",slime);
            rows.add(row);
            level.setBlock(pos,Blocks.AIR.defaultBlockState(),2|16);level.setBlock(pos.below(),Blocks.AIR.defaultBlockState(),2|16);
        }
        return rows;
    }
    private synchronized void saveReport() throws Exception {
        Files.writeString(directory.resolve("minecraft-verification.json"),new GsonBuilder().setPrettyPrinting().create().toJson(report));
    }
    private synchronized void fail(Throwable error) {
        error.printStackTrace();
        try {report.addProperty("status","failed");report.addProperty("error",error.toString());saveReport();}catch(Exception ignored){}
        Minecraft mc=Minecraft.getInstance();if(mc!=null)mc.execute(mc::stop);
    }
}
