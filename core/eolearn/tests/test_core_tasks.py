"""
Credits:
Copyright (c) 2017-2022 Matej Aleksandrov, Matej Batič, Grega Milčinski, Domagoj Korais, Matic Lubej (Sinergise)
Copyright (c) 2017-2022 Žiga Lukšič, Devis Peressutti, Tomislav Slijepčević, Nejc Vesel, Jovan Višnjić (Sinergise)
Copyright (c) 2017-2022 Anže Zupanc (Sinergise)
Copyright (c) 2019-2020 Jernej Puc, Lojze Žust (Sinergise)
Copyright (c) 2017-2019 Blaž Sovdat, Andrej Burja (Sinergise)

This source code is licensed under the MIT license found in the LICENSE
file in the root directory of this source tree.
"""

import copy
import datetime
import pickle
from typing import Dict, Iterable, Tuple, Union

import numpy as np
import pytest
from fs.osfs import OSFS
from fs.tempfs import TempFS
from fs_s3fs import S3FS
from numpy.testing import assert_equal
from pytest import approx

from sentinelhub import CRS

from eolearn.core import (
    AddFeatureTask,
    CopyTask,
    CreateEOPatchTask,
    DeepCopyTask,
    DuplicateFeatureTask,
    EOPatch,
    ExtractBandsTask,
    FeatureType,
    InitializeFeatureTask,
    LoadTask,
    MapFeatureTask,
    MergeEOPatchesTask,
    MergeFeatureTask,
    MoveFeatureTask,
    RemoveFeatureTask,
    RenameFeatureTask,
    SaveTask,
    ZipFeatureTask,
)
from eolearn.core.core_tasks import ExplodeBandsTask


@pytest.fixture(name="patch")
def patch_fixture():
    patch = EOPatch()
    patch.data["bands"] = np.arange(2 * 3 * 3 * 2).reshape(2, 3, 3, 2)
    patch.mask_timeless["mask"] = np.arange(3 * 3 * 2).reshape(3, 3, 2)
    patch.scalar["values"] = np.arange(10 * 5).reshape(10, 5)
    patch.timestamp = [
        datetime.datetime(2017, 1, 1, 10, 4, 7),
        datetime.datetime(2017, 1, 4, 10, 14, 5),
        datetime.datetime(2017, 1, 11, 10, 3, 51),
        datetime.datetime(2017, 1, 14, 10, 13, 46),
        datetime.datetime(2017, 1, 24, 10, 14, 7),
        datetime.datetime(2017, 2, 10, 10, 1, 32),
        datetime.datetime(2017, 2, 20, 10, 6, 35),
        datetime.datetime(2017, 3, 2, 10, 0, 20),
        datetime.datetime(2017, 3, 12, 10, 7, 6),
        datetime.datetime(2017, 3, 15, 10, 12, 14),
    ]
    patch.bbox = (324.54, 546.45, 955.4, 63.43, 3857)
    patch.meta_info["something"] = np.random.rand(10, 1)
    return patch


def test_copy(patch):
    patch_copy = CopyTask().execute(patch)

    assert patch == patch_copy, "Copied patch is different"

    patch_copy.data["new"] = np.arange(1).reshape(1, 1, 1, 1)
    assert "new" not in patch.data, "Dictionary of features was not copied"

    patch_copy.data["bands"][0, 0, 0, 0] += 1
    assert np.array_equal(patch.data["bands"], patch_copy.data["bands"]), "Data should not be copied"


def test_deepcopy(patch):
    patch_deepcopy = DeepCopyTask().execute(patch)

    assert patch == patch_deepcopy, "Deep copied patch is different"

    patch_deepcopy.data["new"] = np.arange(1).reshape(1, 1, 1, 1)
    assert "new" not in patch.data, "Dictionary of features was not copied"

    patch_deepcopy.data["bands"][0, 0, 0, 0] += 1
    assert not np.array_equal(patch.data["bands"], patch_deepcopy.data["bands"]), "Data should be copied"


def test_partial_copy(patch):
    partial_copy = DeepCopyTask(features=[(FeatureType.MASK_TIMELESS, "mask"), FeatureType.BBOX]).execute(patch)
    expected_patch = EOPatch(mask_timeless=patch.mask_timeless, bbox=patch.bbox)
    assert partial_copy == expected_patch, "Partial copying was not successful"

    partial_deepcopy = DeepCopyTask(features=[FeatureType.TIMESTAMP, (FeatureType.SCALAR, "values")]).execute(patch)
    expected_patch = EOPatch(scalar=patch.scalar, timestamp=patch.timestamp)
    assert partial_deepcopy == expected_patch, "Partial deep copying was not successful"


def test_load_task(test_eopatch_path):
    full_load = LoadTask(test_eopatch_path)
    full_patch = full_load.execute(eopatch_folder=".")
    assert len(full_patch.get_features()) == 30

    partial_load = LoadTask(test_eopatch_path, features=[FeatureType.BBOX, FeatureType.MASK_TIMELESS])
    partial_patch = partial_load.execute(eopatch_folder=".")

    assert FeatureType.BBOX in partial_patch and FeatureType.TIMESTAMP not in partial_patch

    load_more = LoadTask(test_eopatch_path, features=[FeatureType.TIMESTAMP])
    upgraded_partial_patch = load_more.execute(partial_patch, eopatch_folder=".")
    assert FeatureType.BBOX in upgraded_partial_patch and FeatureType.TIMESTAMP in upgraded_partial_patch
    assert FeatureType.DATA not in upgraded_partial_patch


def test_load_nothing():
    load = LoadTask("./some/fake/path")
    eopatch = load.execute(eopatch_folder=None)

    assert eopatch == EOPatch()


def test_save_nothing(patch):
    temp_path = "/some/fake/path"
    with TempFS() as temp_fs:
        save = SaveTask(temp_path, filesystem=temp_fs)
        output = save.execute(patch, eopatch_folder=None)

        assert not temp_fs.exists(temp_path)
        assert output == patch


@pytest.mark.parametrize("filesystem", [OSFS("."), S3FS("s3://fake-bucket/"), TempFS()])
@pytest.mark.parametrize("task_class", [LoadTask, SaveTask])
def test_io_task_pickling(filesystem, task_class):
    task = task_class("/", filesystem=filesystem)

    pickled_task = pickle.dumps(task)
    unpickled_task = pickle.loads(pickled_task)
    assert isinstance(unpickled_task, task_class)


def test_add_rename_remove_feature(patch):
    cloud_mask = np.arange(10).reshape(5, 2, 1, 1)
    feature_name = "CLOUD MASK"
    new_feature_name = "CLM"

    patch = copy.deepcopy(patch)

    patch = AddFeatureTask((FeatureType.MASK, feature_name))(patch, cloud_mask)
    assert np.array_equal(patch.mask[feature_name], cloud_mask), "Feature was not added"

    patch = RenameFeatureTask((FeatureType.MASK, feature_name, new_feature_name))(patch)
    assert np.array_equal(patch.mask[new_feature_name], cloud_mask), "Feature was not renamed"
    assert feature_name not in patch[FeatureType.MASK], "Old feature still exists"

    patch = RemoveFeatureTask((FeatureType.MASK, new_feature_name))(patch)
    assert feature_name not in patch.mask, "Feature was not removed"

    patch = RemoveFeatureTask((FeatureType.MASK_TIMELESS, ...))(patch)
    assert len(patch.mask_timeless) == 0, "mask_timeless features were not removed"

    patch = RemoveFeatureTask((FeatureType.MASK, ...))(patch)
    assert len(patch.mask) == 0, "mask features were not removed"


def test_duplicate_feature(patch):
    mask_data = np.arange(10).reshape(5, 2, 1, 1)
    feature_name = "MASK1"
    duplicate_name = "MASK2"

    patch = AddFeatureTask((FeatureType.MASK, feature_name))(patch, mask_data)

    duplicate_task = DuplicateFeatureTask((FeatureType.MASK, feature_name, duplicate_name))
    patch = duplicate_task(patch)

    assert duplicate_name in patch.mask, "Feature was not duplicated. Name not found."
    assert id(patch.mask["MASK1"]) == id(patch.mask["MASK2"])
    assert np.array_equal(
        patch.mask[duplicate_name], mask_data
    ), "Feature was not duplicated correctly. Data does not match."

    with pytest.raises(ValueError):
        # Expected a ValueError when creating an already exising feature.
        patch = duplicate_task(patch)

    duplicate_names = {"D1", "D2"}
    feature_list = [(FeatureType.MASK, "MASK1", "D1"), (FeatureType.MASK, "MASK2", "D2")]
    patch = DuplicateFeatureTask(feature_list).execute(patch)

    assert duplicate_names.issubset(patch.mask), "Duplicating multiple features failed."

    patch = DuplicateFeatureTask((FeatureType.MASK, "MASK1", "DEEP"), deep_copy=True)(patch)
    assert id(patch.mask["MASK1"]) != id(patch.mask["DEEP"])
    assert np.array_equal(
        patch.mask["MASK1"], patch.mask["DEEP"]
    ), "Feature was not duplicated correctly. Data does not match."

    # Duplicating MASK1 three times into D3, D4, D5 doesn't work, because EOTask.feature_gen
    # returns a dict containing only ('MASK1', 'D5') duplication

    duplicate_names = {"D3", "D4", "D5"}
    feature_list = [(FeatureType.MASK, "MASK1", new) for new in duplicate_names]
    patch = DuplicateFeatureTask(feature_list).execute(patch)

    assert duplicate_names.issubset(patch.mask), "Duplicating single feature multiple times failed."


def test_initialize_feature(patch):
    patch = DeepCopyTask()(patch)

    init_val = 123
    shape = (5, 10, 10, 3)
    compare_data = np.ones(shape) * init_val

    patch = InitializeFeatureTask((FeatureType.MASK, "test"), shape=shape, init_value=init_val)(patch)
    assert patch.mask["test"].shape == shape
    assert np.array_equal(patch.mask["test"], compare_data)

    with pytest.raises(ValueError):
        # Expected a ValueError when trying to initialize a feature with a wrong shape dimensions.
        patch = InitializeFeatureTask((FeatureType.MASK_TIMELESS, "wrong"), shape=shape, init_value=init_val)(patch)

    init_val = 123
    shape = (10, 10, 3)
    compare_data = np.ones(shape) * init_val

    patch = InitializeFeatureTask((FeatureType.MASK_TIMELESS, "test"), shape=shape, init_value=init_val)(patch)
    assert patch.mask_timeless["test"].shape == shape
    assert np.array_equal(patch.mask_timeless["test"], compare_data)

    with pytest.raises(ValueError):
        # Expected a ValueError when trying to initialize a feature with a wrong shape dimensions.
        patch = InitializeFeatureTask((FeatureType.MASK, "wrong"), shape=shape, init_value=init_val)(patch)

    init_val = 123
    shape = (5, 10, 10, 3)
    compare_data = np.ones(shape) * init_val
    new_names = ("F1", "F2", "F3")

    patch = InitializeFeatureTask({FeatureType.MASK: new_names}, shape=shape, init_value=init_val)(patch)
    assert set(new_names) < set(patch.mask), "Failed to initialize new features from a shape tuple."
    assert all(patch.mask[key].shape == shape for key in new_names)
    assert all(np.array_equal(patch.mask[key], compare_data) for key in new_names)

    patch = InitializeFeatureTask({FeatureType.DATA: new_names}, shape=(FeatureType.DATA, "bands"))(patch)
    assert set(new_names) < set(patch.data), "Failed to initialize new features from an existing feature."
    assert all(patch.data[key].shape == patch.data["bands"].shape for key in new_names)

    with pytest.raises(ValueError):
        InitializeFeatureTask({FeatureType.DATA: new_names}, 1234)


def test_move_feature():
    patch_src = EOPatch()
    patch_dst = EOPatch()

    shape = (10, 5, 5, 3)
    size = np.product(shape)

    shape_timeless = (5, 5, 3)
    size_timeless = np.product(shape_timeless)

    data = [np.random.randint(0, 100, size).reshape(*shape) for i in range(3)] + [
        np.random.randint(0, 100, size_timeless).reshape(*shape_timeless) for i in range(2)
    ]

    features = [
        (FeatureType.DATA, "D1"),
        (FeatureType.DATA, "D2"),
        (FeatureType.MASK, "M1"),
        (FeatureType.MASK_TIMELESS, "MTless1"),
        (FeatureType.MASK_TIMELESS, "MTless2"),
    ]

    for feat, dat in zip(features, data):
        patch_src = AddFeatureTask(feat)(patch_src, dat)

    patch_dst = MoveFeatureTask(features)(patch_src, patch_dst)

    for i, feature in enumerate(features):
        assert id(data[i]) == id(patch_dst[feature])
        assert np.array_equal(data[i], patch_dst[feature])

    patch_dst = EOPatch()
    patch_dst = MoveFeatureTask(features, deep_copy=True)(patch_src, patch_dst)

    for i, feature in enumerate(features):
        assert id(data[i]) != id(patch_dst[feature])
        assert np.array_equal(data[i], patch_dst[feature])

    features = [(FeatureType.MASK_TIMELESS, ...)]
    patch_dst = EOPatch()
    patch_dst = MoveFeatureTask(features)(patch_src, patch_dst)

    assert FeatureType.DATA not in patch_dst, "FeatureType.DATA features were moved but shouldn't be."

    assert (FeatureType.MASK_TIMELESS, "MTless1") in patch_dst
    assert (FeatureType.MASK_TIMELESS, "MTless2") in patch_dst


@pytest.mark.parametrize("axis", (0, -1))
def test_merge_features(axis):
    patch = EOPatch()

    shape = (10, 5, 5, 3)
    size = np.product(shape)

    shape_timeless = (5, 5, 3)
    size_timeless = np.product(shape_timeless)

    data = [np.random.randint(0, 100, size).reshape(*shape) for _ in range(3)] + [
        np.random.randint(0, 100, size_timeless).reshape(*shape_timeless) for _ in range(2)
    ]

    features = [
        (FeatureType.DATA, "D1"),
        (FeatureType.DATA, "D2"),
        (FeatureType.MASK, "M1"),
        (FeatureType.MASK_TIMELESS, "MTless1"),
        (FeatureType.MASK_TIMELESS, "MTless2"),
    ]

    for feat, dat in zip(features, data):
        patch = AddFeatureTask(feat)(patch, dat)

    patch = MergeFeatureTask(features[:3], (FeatureType.MASK, "merged"), axis=axis)(patch)
    patch = MergeFeatureTask(features[3:], (FeatureType.MASK_TIMELESS, "merged_timeless"), axis=axis)(patch)

    expected = np.concatenate([patch[f] for f in features[:3]], axis=axis)

    assert np.array_equal(patch.mask["merged"], expected)


def test_zip_features(test_eopatch):
    merge = ZipFeatureTask(
        {FeatureType.DATA: ["CLP", "NDVI", "BANDS-S2-L1C"]},  # input features
        (FeatureType.DATA, "MERGED"),  # output feature
        lambda *f: np.concatenate(f, axis=-1),
    )

    patch = merge(test_eopatch)

    expected = np.concatenate([patch.data["CLP"], patch.data["NDVI"], patch.data["BANDS-S2-L1C"]], axis=-1)
    assert np.array_equal(patch.data["MERGED"], expected)

    zip_fail = ZipFeatureTask({FeatureType.DATA: ["CLP", "NDVI"]}, (FeatureType.DATA, "MERGED"))
    with pytest.raises(NotImplementedError):
        zip_fail(patch)


def test_map_features(test_eopatch):
    move = MapFeatureTask(
        {FeatureType.DATA: ["CLP", "NDVI", "BANDS-S2-L1C"]},
        {FeatureType.DATA: ["CLP2", "NDVI2", "BANDS-S2-L1C2"]},
        copy.deepcopy,
    )

    patch = move(test_eopatch)

    assert np.array_equal(patch.data["CLP"], patch.data["CLP2"])
    assert np.array_equal(patch.data["NDVI"], patch.data["NDVI2"])
    assert np.array_equal(patch.data["BANDS-S2-L1C"], patch.data["BANDS-S2-L1C2"])

    assert id(patch.data["CLP"]) != id(patch.data["CLP2"])
    assert id(patch.data["NDVI"]) != id(patch.data["NDVI2"])
    assert id(patch.data["BANDS-S2-L1C"]) != id(patch.data["BANDS-S2-L1C2"])

    map_fail = MapFeatureTask(
        {FeatureType.DATA: ["CLP", "NDVI"]},
        {
            FeatureType.DATA: [
                "CLP2",
                "NDVI2",
            ]
        },
    )
    with pytest.raises(NotImplementedError):
        map_fail(patch)

    f_in, f_out = {FeatureType.DATA: ["CLP", "NDVI"]}, {FeatureType.DATA: ["CLP2"]}
    with pytest.raises(ValueError):
        MapFeatureTask(f_in, f_out)


@pytest.mark.parametrize(
    "feature,  task_input",
    [
        ((FeatureType.DATA, "REFERENCE_SCENES"), {(FeatureType.DATA, "MOVED_BANDS"): [2, 4, 8]}),
        ((FeatureType.DATA, "REFERENCE_SCENES"), {(FeatureType.DATA, "MOVED_BANDS"): [2]}),
        ((FeatureType.DATA, "REFERENCE_SCENES"), {(FeatureType.DATA, "MOVED_BANDS"): (2,)}),
        ((FeatureType.DATA, "REFERENCE_SCENES"), {(FeatureType.DATA, "MOVED_BANDS"): 2}),
        (
            (FeatureType.DATA, "REFERENCE_SCENES"),
            {(FeatureType.DATA, "B01"): [0], (FeatureType.DATA, "B02"): [1], (FeatureType.DATA, "B02 & B03"): [1, 2]},
        ),
        ((FeatureType.DATA, "REFERENCE_SCENES"), {(FeatureType.DATA, "MOVED_BANDS"): []}),
    ],
)
def test_explode_bands(
    test_eopatch: EOPatch,
    feature: FeatureType,
    task_input: Dict[Tuple[FeatureType, str], Union[int, Iterable[int]]],
):
    move_bands = ExplodeBandsTask(feature, task_input)
    patch = move_bands(test_eopatch)
    assert all(new_feature in patch for new_feature in task_input)

    for new_feature, bands in task_input.items():
        if isinstance(bands, int):
            bands = [bands]
        assert_equal(patch[new_feature], test_eopatch[feature][..., bands])


def test_extract_bands(test_eopatch):
    bands = [2, 4, 8]
    move_bands = ExtractBandsTask((FeatureType.DATA, "REFERENCE_SCENES"), (FeatureType.DATA, "MOVED_BANDS"), bands)
    patch = move_bands(test_eopatch)
    assert np.array_equal(patch.data["MOVED_BANDS"], patch.data["REFERENCE_SCENES"][..., bands])

    old_value = patch.data["MOVED_BANDS"][0, 0, 0, 0]
    patch.data["MOVED_BANDS"][0, 0, 0, 0] += 1.0
    assert patch.data["REFERENCE_SCENES"][0, 0, 0, bands[0]] == old_value
    assert old_value + 1.0 == approx(patch.data["MOVED_BANDS"][0, 0, 0, 0])

    bands = [2, 4, 16]
    move_bands = ExtractBandsTask((FeatureType.DATA, "REFERENCE_SCENES"), (FeatureType.DATA, "MOVED_BANDS"), bands)
    with pytest.raises(ValueError):
        move_bands(patch)


def test_create_eopatch():
    data = np.arange(2 * 3 * 3 * 2).reshape(2, 3, 3, 2)
    bbox = [5.60, 52.68, 5.75, 52.63, CRS.WGS84]

    patch = CreateEOPatchTask()(data={"bands": data}, bbox=bbox)
    assert np.array_equal(patch.data["bands"], data)


def test_kwargs():
    patch = EOPatch()
    shape = (3, 5, 5, 2)

    data1 = np.random.randint(0, 5, size=shape)
    data2 = np.random.randint(0, 5, size=shape)

    patch[(FeatureType.DATA, "D1")] = data1
    patch[(FeatureType.DATA, "D2")] = data2

    task0 = MapFeatureTask((FeatureType.DATA, "D1"), (FeatureType.DATA_TIMELESS, "NON_ZERO"), np.count_nonzero, axis=0)

    task1 = MapFeatureTask((FeatureType.DATA, "D1"), (FeatureType.DATA_TIMELESS, "MAX1"), np.max, axis=0)

    task2 = ZipFeatureTask({FeatureType.DATA: ["D1", "D2"]}, (FeatureType.DATA, "MAX2"), np.maximum, dtype=np.float32)

    patch = task0(patch)
    patch = task1(patch)
    patch = task2(patch)

    assert np.array_equal(patch[(FeatureType.DATA_TIMELESS, "NON_ZERO")], np.count_nonzero(data1, axis=0))
    assert np.array_equal(patch[(FeatureType.DATA_TIMELESS, "MAX1")], np.max(data1, axis=0))
    assert np.array_equal(patch[(FeatureType.DATA, "MAX2")], np.maximum(data1, data2))


def test_merge_eopatches(test_eopatch):
    task = MergeEOPatchesTask(time_dependent_op="max", timeless_op="concatenate")

    del test_eopatch.data["REFERENCE_SCENES"]  # wrong time dimension

    task.execute(test_eopatch, test_eopatch, test_eopatch)
