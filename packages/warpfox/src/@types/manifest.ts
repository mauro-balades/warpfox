export interface ManifestBrand {
  readonly fullName: string;
  readonly shortName: string;
  readonly shorterName: string;
  readonly version: string;
}

export interface ManifestBrands {
  [key: string]: ManifestBrand;
}

export default interface Manifest {
  brands: ManifestBrands;
  updatesHost?: string;
  firefoxVersion: string;
}
